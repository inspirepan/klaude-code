"""REPL completion handlers for @ file paths, / slash commands, and skills.

This module provides completers for the REPL input:
- _SlashCommandCompleter: Completes slash commands/skills at the effective line start
- _SkillCompleter: Completes inline skill names with / or // prefixes
- _AtFilesCompleter: Completes @path segments using Git or a Python filesystem scan
- _ComboCompleter: Combines all completers with priority logic

Public API:
- create_repl_completer(): Factory function to create the combined completer
- path_matches_query(): Check whether a path fuzzy-matches a query
- AT_TOKEN_PATTERN: Regex pattern for @token matching (used by key bindings)
- SKILL_TOKEN_PATTERN: Regex pattern for skill tokens (used by key bindings)
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import threading
import time
from bisect import insort
from collections import deque
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import NamedTuple

from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.document import Document
from prompt_toolkit.formatted_text import FormattedText

from klaude_code.const import COMPLETER_CACHE_TTL_SEC, COMPLETER_CMD_TIMEOUT_SEC
from klaude_code.log import DebugType, log_debug
from klaude_code.protocol.input_syntax import AT_COMPLETION_PATTERN, SKILL_COMPLETION_PATTERN
from klaude_code.tui.command.types import CommandInfo

# Pattern to match @token for completion refresh (used by key bindings).
# Supports both plain tokens like `@src/file.py` and quoted tokens like
# `@"path with spaces/file.py"` so that filenames with spaces remain a
# single logical token.
AT_TOKEN_PATTERN = AT_COMPLETION_PATTERN

# Pattern to match inline /skill token for skill completion
# (used by key bindings).
# Supports inline matching: after whitespace, at start of line, or after CJK text.
SKILL_TOKEN_PATTERN = SKILL_COMPLETION_PATTERN

_SKILL_PREFIX = "skill:"

_SKILL_LOCATION_STYLE = {
    "project": "class:skill.project",
    "user": "class:skill.user",
    "system": "class:skill.system",
}


def _skill_display(name: str, location: str) -> FormattedText:
    bullet_style = _SKILL_LOCATION_STYLE.get(location, "class:meta")
    return FormattedText([(bullet_style, "•"), ("class:meta", f" {_SKILL_PREFIX}"), ("", name)])


def _command_display(name: str, hint: str) -> FormattedText:
    return FormattedText([("class:meta", "•"), ("", f" {name}"), ("class:meta", hint)])


def _skill_match_rank(name: str, desc: str, frag_lower: str) -> tuple[int, int, int, int, int, int, int] | None:
    """Return rank tuple for skill completion relevance, or None when not matched."""

    name_lower = name.lower()
    desc_lower = desc.lower()
    skill_token_lower = f"{_SKILL_PREFIX}{name}".lower()

    name_prefix = name_lower.startswith(frag_lower)
    segment_prefix = any(seg.startswith(frag_lower) for seg in re.split(r"[-_:]", name_lower) if seg)
    token_prefix = skill_token_lower.startswith(frag_lower)
    name_contains = frag_lower in name_lower
    token_contains = frag_lower in skill_token_lower
    desc_contains = frag_lower in desc_lower

    if not (name_contains or token_contains or desc_contains):
        return None

    return (
        0 if name_prefix else 1,
        0 if segment_prefix else 1,
        0 if token_prefix else 1,
        0 if name_contains else 1,
        0 if token_contains else 1,
        0 if desc_contains else 1,
        len(name_lower),
    )


type _PathMatchRank = tuple[int, int, int, int, int]
type _PathSortKey = tuple[int, int, int, int, int, int, int, int, int]
type _RankedPath = tuple[_PathSortKey, str, str]


def _path_match_rank(path: str, query: str) -> _PathMatchRank | None:
    """Return a path-aware fuzzy rank, or None when the query does not match."""
    normalized = path.removeprefix("./").removeprefix(".\\").rstrip("/")
    path_lower = normalized.lower()
    query_lower = query.lower()
    if not query_lower:
        return (0, 0, 0, 0, 0)

    basename_offset = path_lower.rfind("/") + 1
    basename = path_lower[basename_offset:]
    stem = basename.rsplit(".", 1)[0] if "." in basename and not basename.startswith(".") else basename

    if stem == query_lower:
        return (0, 0, 0, 0, basename_offset)
    if basename.startswith(query_lower):
        return (1, 0, 0, 0, basename_offset)

    basename_pos = basename.find(query_lower)
    if basename_pos >= 0:
        return (2, 0, 0, 0, basename_offset + basename_pos)

    path_pos = path_lower.find(query_lower)
    if path_pos >= 0:
        return (3, 0, 0, 0, path_pos)

    preserves_indices = len(normalized) == len(path_lower)

    def is_boundary(index: int) -> bool:
        return (
            index == 0
            or path_lower[index - 1] in "/\\._- "
            or (
                preserves_indices
                and normalized[index].isupper()
                and normalized[index - 1].islower()
            )
        )

    # For every endpoint, retain the best partial subsequence ending there.
    # The state is (-boundary_hits, total_gap, runs, start_position).
    states: dict[int, tuple[int, int, int, int]] = {
        index: (-int(is_boundary(index)), 0, 1, index)
        for index, char in enumerate(path_lower)
        if char == query_lower[0]
    }
    for query_char in query_lower[1:]:
        next_states: dict[int, tuple[int, int, int, int]] = {}
        for index, char in enumerate(path_lower):
            if char != query_char:
                continue
            candidates = []
            for previous_index, state in states.items():
                if previous_index >= index:
                    continue
                step_gap = index - previous_index - 1
                candidates.append(
                    (
                        state[0] - int(is_boundary(index)),
                        state[1] + step_gap,
                        state[2] + int(step_gap > 0),
                        state[3],
                    )
                )
            if candidates:
                next_states[index] = min(candidates)
        states = next_states
        if not states:
            return None

    if not states:
        return None

    boundary_score, gap, runs, start = min(states.values())
    if boundary_score == 0 and gap > max(12, len(query_lower) * 4):
        return None
    return (4 if start >= basename_offset else 5, boundary_score, gap, runs, start)


def path_matches_query(path: str, query: str) -> bool:
    """Return whether query fuzzy-matches path as an ordered subsequence."""
    return _path_match_rank(path, query) is not None


def _path_sort_key(path: str, query: str) -> _PathSortKey | None:
    match_rank = _path_match_rank(path, query)
    if match_rank is None:
        return None

    normalized = path.removeprefix("./").removeprefix(".\\")
    path_lower = normalized.lower()
    is_hidden = any(segment.startswith(".") for segment in normalized.split("/") if segment)
    has_test = "test" in path_lower
    depth = normalized.rstrip("/").count("/")
    return (1 if is_hidden else 0, 1 if has_test else 0, *match_rank, depth, len(normalized))


def _add_ranked_path(ranked: list[_RankedPath], path: str, query: str, *, limit: int) -> bool:
    """Insert a matching path into a bounded sorted list and report overflow."""
    rank = _path_sort_key(path, query)
    if rank is None:
        return False

    insort(ranked, (rank, path.lower(), path))
    if len(ranked) <= limit:
        return False
    ranked.pop()
    return True


def create_repl_completer(
    command_info_provider: Callable[[], list[CommandInfo]] | None = None,
) -> Completer:
    """Create and return the combined REPL completer.

    Args:
        command_info_provider: Optional callable that returns command metadata.
            If None, slash command completion is disabled.

    Returns a completer that handles both @ file paths and / slash commands.
    """
    return _ComboCompleter(command_info_provider=command_info_provider)


class _CmdResult(NamedTuple):
    """Result of running an external command."""

    ok: bool
    lines: list[str]


def _is_at_effective_line_start(document: Document) -> bool:
    """Return True when all text before the current line is whitespace.

    This treats a command-style completion context as valid on any row as long
    as the user has only typed blank/whitespace lines before the current one.
    """
    text = document.text_before_cursor
    last_newline = text.rfind("\n")
    preceding = "" if last_newline < 0 else text[: last_newline + 1]
    return preceding.strip() == ""


class _SlashCommandCompleter(Completer):
    """Complete slash commands/skills at the effective start of input.

    Behavior:
    - `/...`: shows command + skill completions (command first)
      - Command prefix match is always enabled
      - When fragment length > 4, also include command name/summary contains-match after prefix matches
    - `//...`: shows only skill completions
    - Inserts trailing space after completion
    - Triggers on the first line, or on any later line when all preceding
      lines are blank/whitespace.
    """

    # Allows optional leading whitespace on the current line; the completion
    # replaces the leading whitespace too so the inserted text starts with `/`.
    _SLASH_TOKEN_RE = re.compile(r"^(?P<lead>\s*)(?P<prefix>//|/)(?P<frag>[^\s/]*)$")

    def __init__(self, command_info_provider: Callable[[], list[CommandInfo]] | None = None) -> None:
        self._command_info_provider = command_info_provider

    def get_completions(
        self,
        document: Document,
        complete_event,  # type: ignore[override]
    ) -> Iterable[Completion]:
        # Allow completion when cursor is on a line whose preceding lines are blank
        if not _is_at_effective_line_start(document):
            return

        if self._command_info_provider is None:
            command_infos: list[CommandInfo] = []
        else:
            command_infos = self._command_info_provider()

        text_before = document.current_line_before_cursor
        m = self._SLASH_TOKEN_RE.search(text_before)
        if not m:
            return

        prefix = m.group("prefix")
        frag = m.group("frag")
        # Replace from the start of the leading whitespace (if any) so the
        # inserted command/skill token begins at the line start.
        start_position = -len(text_before)  # negative offset covering lead + prefix + frag

        skills = self._get_available_skills()
        frag_lower = frag.lower()
        if frag_lower == "":
            matched_skills = skills
        else:
            ranked_skills: list[tuple[tuple[int, int, int, int, int, int, int], str, str, str]] = []
            for name, desc, location in skills:
                rank = _skill_match_rank(name, desc, frag_lower)
                if rank is not None:
                    ranked_skills.append((rank, name, desc, location))
            ranked_skills.sort(key=lambda x: x[0])
            matched_skills = [(name, desc, location) for _, name, desc, location in ranked_skills]

        if prefix == "/":
            allow_contains_match = len(frag_lower) > 4

            matched_prefix: list[CommandInfo] = []
            matched_name_contains: list[CommandInfo] = []
            matched_summary_contains: list[CommandInfo] = []

            for cmd_info in command_infos:
                if cmd_info.name.startswith(frag):
                    matched_prefix.append(cmd_info)
                    continue

                if not allow_contains_match:
                    continue

                name_lower = cmd_info.name.lower()
                summary_lower = cmd_info.summary.lower()
                if frag_lower in name_lower:
                    matched_name_contains.append(cmd_info)
                elif frag_lower in summary_lower:
                    matched_summary_contains.append(cmd_info)

            for cmd_info in [*matched_prefix, *matched_name_contains, *matched_summary_contains]:
                hint = f" [{cmd_info.placeholder}]" if cmd_info.support_addition_params else ""
                yield Completion(
                    text=f"/{cmd_info.name} ",
                    start_position=start_position,
                    display=_command_display(cmd_info.name, hint),
                    display_meta=cmd_info.summary,
                )

        for name, desc, location in matched_skills:
            yield Completion(
                text=f"{prefix}{_SKILL_PREFIX}{name} ",
                start_position=start_position,
                display=_skill_display(name, location),
                display_meta=desc,
            )

    def is_slash_command_context(self, document: Document) -> bool:
        """Check if current context is slash completion at effective line start."""
        if not _is_at_effective_line_start(document):
            return False
        text_before = document.current_line_before_cursor
        return bool(self._SLASH_TOKEN_RE.search(text_before))

    def _get_available_skills(self) -> list[tuple[str, str, str]]:
        try:
            from klaude_code.skill import get_available_skills

            return get_available_skills()
        except (ImportError, RuntimeError):
            return []


class _SkillCompleter(Completer):
    """Complete skill names with / or // prefix.

    Behavior:
    - Triggers when cursor is after / or // (at start of line or after whitespace)
    - Shows available skills with descriptions
    - Inserts trailing space after completion
    """

    _SKILL_TOKEN_RE = SKILL_TOKEN_PATTERN

    def get_completions(
        self,
        document: Document,
        complete_event,  # type: ignore[override]
    ) -> Iterable[Completion]:
        text_before = document.current_line_before_cursor
        m = self._SKILL_TOKEN_RE.search(text_before)
        if not m:
            return

        prefix = m.group("prefix")
        frag = m.group("frag").lower()
        # Calculate token start: the match includes optional leading whitespace
        token_len = len(prefix) + len(m.group("frag"))
        token_start = len(text_before) - token_len
        start_position = token_start - len(text_before)  # negative offset

        # Get available skills from SkillTool
        skills = self._get_available_skills()
        if not skills:
            return

        # Filter skills that match the fragment (case-insensitive)
        if frag == "":
            matched = skills
        else:
            ranked: list[tuple[tuple[int, int, int, int, int, int, int], str, str, str]] = []
            for name, desc, location in skills:
                rank = _skill_match_rank(name, desc, frag)
                if rank is not None:
                    ranked.append((rank, name, desc, location))
            ranked.sort(key=lambda x: x[0])
            matched = [(name, desc, location) for _, name, desc, location in ranked]

        if not matched:
            return

        for name, desc, location in matched:
            completion_text = f"{prefix}{_SKILL_PREFIX}{name} "
            yield Completion(
                text=completion_text,
                start_position=start_position,
                display=_skill_display(name, location),
                display_meta=desc,
            )

    def _get_available_skills(self) -> list[tuple[str, str, str]]:
        """Get available skills from skill module.

        Returns:
            List of (name, description, location) tuples
        """
        try:
            # Import here to avoid circular imports
            from klaude_code.skill import get_available_skills

            return get_available_skills()
        except (ImportError, RuntimeError):
            return []

    def is_skill_context(self, document: Document) -> bool:
        """Check if current context is a skill completion."""
        text_before = document.current_line_before_cursor
        return bool(self._SKILL_TOKEN_RE.search(text_before))


class _ComboCompleter(Completer):
    """Combined completer that handles @ file paths, slash commands, and skills."""

    def __init__(self, command_info_provider: Callable[[], list[CommandInfo]] | None = None) -> None:
        self._at_completer = _AtFilesCompleter()
        self._slash_completer = _SlashCommandCompleter(command_info_provider=command_info_provider)
        self._skill_completer = _SkillCompleter()

    def get_completions(
        self,
        document: Document,
        complete_event,  # type: ignore[override]
    ) -> Iterable[Completion]:
        # Bash mode: disable all completions.
        # A command is considered bash mode only when the first character is `!` (or full-width `！`).
        try:
            if document.text.startswith(("!", "！")):
                return
        except Exception:
            pass

        # Try slash command completion first (first line, or later lines whose preceding content is blank)
        if self._slash_completer.is_slash_command_context(document):
            yield from self._slash_completer.get_completions(document, complete_event)
            return

        # Try inline skill completion
        if self._skill_completer.is_skill_context(document):
            yield from self._skill_completer.get_completions(document, complete_event)
            return

        # Fall back to @ file completion
        yield from self._at_completer.get_completions(document, complete_event)


class _AtFilesCompleter(Completer):
    """Complete @path segments using Git or a Python filesystem scan.

    Behavior:
    - Only triggers when the cursor is after an "@…" token (until whitespace).
    - Completes paths relative to the current working directory.
    - Uses the Git index inside repositories and an in-process scan elsewhere.
    - Caches Git indexes and query results to avoid excessive spawning.
    - Inserts a trailing space after completion to stop further triggering.
    """

    _AT_TOKEN_RE = AT_TOKEN_PATTERN
    _FILESYSTEM_SCAN_TIMEOUT_SEC = 0.15
    _FILESYSTEM_SCAN_MAX_ENTRIES = 50_000

    def __init__(
        self,
        cache_ttl_sec: float = COMPLETER_CACHE_TTL_SEC,
        max_results: int = 20,
    ):
        self._cache_ttl = cache_ttl_sec
        self._max_results = max_results

        # Query result cache
        self._last_query_key: str | None = None
        self._last_results: list[str] = []
        self._last_results_time: float = 0.0

        # git ls-files cache (preferred when inside a git repo)
        self._git_repo_root: Path | None = None
        self._git_repo_root_time: float = 0.0
        self._git_repo_root_cwd: Path | None = None

        self._git_file_list: list[str] | None = None
        self._git_dir_list: list[str] | None = None
        self._git_file_list_time: float = 0.0
        self._git_file_list_cwd: Path | None = None

        # Path searches are bounded and never overlap. ThreadedCompleter does
        # not cancel an in-flight generator when the user types another key.
        self._path_search_lock = threading.Lock()
        self._filesystem_scan_timeout_sec = self._FILESYSTEM_SCAN_TIMEOUT_SEC
        self._filesystem_scan_max_entries = self._FILESYSTEM_SCAN_MAX_ENTRIES

        # Command timeout is intentionally higher than a keypress cadence.
        # Git discovery and file lists are cached across completion requests.
        self._cmd_timeout_sec: float = COMPLETER_CMD_TIMEOUT_SEC

    # ---- prompt_toolkit API ----
    def get_completions(self, document: Document, complete_event) -> Iterable[Completion]:  # type: ignore[override]
        text_before = document.text_before_cursor
        m = self._AT_TOKEN_RE.search(text_before)
        if not m:
            return []  # type: ignore[reportUnknownVariableType]

        frag = m.group("frag")  # raw text after '@' and before cursor (may be quoted)
        # Normalize fragment for search: support optional quoting syntax @"…".
        is_quoted = frag.startswith('"')
        search_frag = frag
        if is_quoted:
            # Drop leading quote; if user already closed the quote, drop trailing quote as well.
            search_frag = search_frag[1:]
            if search_frag.endswith('"'):
                search_frag = search_frag[:-1]

        token_start_in_input = len(text_before) - len(f"@{frag}")

        cwd = Path.cwd()

        # If no fragment yet, show lightweight suggestions from current directory
        if search_frag.strip() == "":
            suggestions = self._suggest_for_empty_fragment(cwd)
            if not suggestions:
                return []  # type: ignore[reportUnknownVariableType]
            start_position = token_start_in_input - len(text_before)
            for s in suggestions[: self._max_results]:
                yield Completion(
                    text=self._format_completion_text(s, is_quoted=is_quoted),
                    start_position=start_position,
                    display=self._format_display_label(s),
                )
            return []  # type: ignore[reportUnknownVariableType]

        # Gather suggestions with debounce/caching based on search keyword
        suggestions = self._complete_paths(cwd, search_frag)
        if not suggestions:
            return []  # type: ignore[reportUnknownVariableType]

        # Prepare Completion objects. Replace from the '@' character.
        start_position = token_start_in_input - len(text_before)  # negative
        for s in suggestions[: self._max_results]:
            yield Completion(
                text=self._format_completion_text(s, is_quoted=is_quoted),
                start_position=start_position,
                display=self._format_display_label(s),
            )

    # ---- Core logic ----
    def _complete_paths(self, cwd: Path, keyword: str) -> list[str]:
        now = time.monotonic()
        key_norm = keyword.lower()
        query_key = f"{cwd.resolve()}::search::{key_norm}"

        max_scan_results = self._max_results * 3

        # Cache TTL: reuse cached results for same query within TTL
        if self._last_results and self._last_query_key == query_key and now - self._last_results_time < self._cache_ttl:
            return self._filter_and_format(self._last_results, cwd, key_norm)

        # Git provides the bounded path index inside repositories. Scanning is
        # reserved for non-Git directories or environments without Git.
        if self._get_git_repo_root(cwd) is not None:
            results, _truncated = self._git_paths_for_keyword(cwd, key_norm, max_results=max_scan_results)
        else:
            results, _truncated = self._python_paths_for_keyword(cwd, key_norm, max_results=max_scan_results)

        if not results:
            return []

        # Update caches
        self._last_query_key = query_key
        self._last_results = results
        self._last_results_time = now
        return self._filter_and_format(results, cwd, key_norm)

    def _filter_and_format(
        self,
        paths_from_root: list[str],
        cwd: Path,
        keyword_norm: str,
    ) -> list[str]:
        out: list[tuple[str, tuple[int, int, int, int, int, int, int, int, int]]] = []
        for p in paths_from_root:
            # Path sources return paths relative to cwd. Some Git output can
            # include a leading './' prefix; strip that exact prefix only.
            #
            # Do not use lstrip('./') here: it would also remove the leading '.'
            # from dotfiles/directories like '.claude/'.
            rel_to_cwd = p.removeprefix("./").removeprefix(".\\")
            score = _path_sort_key(rel_to_cwd, keyword_norm)
            if score is not None:
                out.append((rel_to_cwd, score))
        # Sort by score
        out.sort(key=lambda item: (item[1], item[0].lower()))
        # Unique while preserving order
        seen: set[str] = set()
        uniq: list[str] = []
        for s, _ in out:
            if s not in seen:
                seen.add(s)
                uniq.append(s)

        # Append trailing slash for directories, but avoid excessive stats.
        # For large candidate lists, only stat the most relevant prefixes.
        stat_limit = min(len(uniq), max(self._max_results * 3, 60))
        for idx in range(stat_limit):
            s = uniq[idx]
            if s.endswith("/"):
                continue
            try:
                if (cwd / s).is_dir():
                    uniq[idx] = f"{s}/"
            except OSError:
                continue
        return uniq

    def _format_completion_text(self, suggestion: str, *, is_quoted: bool) -> str:
        """Format completion insertion text for a given suggestion.

        Paths that contain whitespace are always wrapped in quotes so that they
        can be parsed correctly by the @-file reader. If the user explicitly
        started a quoted token (e.g. @"foo), we preserve quoting even when the
        suggested path itself does not contain spaces.
        """
        needs_quotes = any(ch.isspace() for ch in suggestion)
        if needs_quotes or is_quoted:
            return f'@"{suggestion}" '
        return f"@{suggestion} "

    def _format_display_label(self, suggestion: str) -> FormattedText:
        """Format visible label showing the full path.

        The filename is shown in default color, directory parts use a dim style.
        """
        is_dir = suggestion.endswith("/")
        stripped = suggestion.rstrip("/")
        basename = stripped.rsplit("/", 1)[-1]
        if is_dir:
            basename += "/"
        dir_prefix = suggestion[: len(suggestion) - len(basename)]

        segments: list[tuple[str, str]] = []
        if dir_prefix:
            segments.append(("class:meta", dir_prefix))
        segments.append(("", basename))

        return FormattedText(segments)

    # ---- Utilities ----
    def _python_paths_for_keyword(self, cwd: Path, keyword_norm: str, *, max_results: int) -> tuple[list[str], bool]:
        """Return bounded fuzzy matches from a breadth-first filesystem scan."""
        if not self._path_search_lock.acquire(blocking=False):
            return [], True

        try:
            return self._scan_python_paths(cwd, keyword_norm, max_results=max_results)
        finally:
            self._path_search_lock.release()

    def _scan_python_paths(self, cwd: Path, keyword_norm: str, *, max_results: int) -> tuple[list[str], bool]:
        excluded = {".git", ".venv", "node_modules"}
        ranked: list[_RankedPath] = []
        pending: deque[tuple[str, str]] = deque([("", str(cwd))])
        deadline = time.monotonic() + self._filesystem_scan_timeout_sec
        scanned = 0
        truncated = False

        while pending:
            rel_dir, directory = pending.popleft()
            try:
                with os.scandir(directory) as entries:
                    for entry in entries:
                        scanned += 1
                        if scanned > self._filesystem_scan_max_entries or time.monotonic() >= deadline:
                            truncated = True
                            pending.clear()
                            break
                        if entry.name in excluded:
                            continue

                        rel = f"{rel_dir}/{entry.name}" if rel_dir else entry.name
                        try:
                            is_dir = entry.is_dir(follow_symlinks=False)
                        except OSError:
                            continue

                        if is_dir:
                            pending.append((rel, entry.path))
                            candidate = f"{rel}/"
                        else:
                            candidate = rel

                        if _add_ranked_path(ranked, candidate, keyword_norm, limit=max_results):
                            truncated = True
            except OSError:
                continue

        return [path for _, _, path in ranked], truncated

    def _git_paths_for_keyword(self, cwd: Path, keyword_norm: str, *, max_results: int) -> tuple[list[str], bool]:
        """Get path suggestions from the git index (fast for large repos).

        Returns (candidates, truncated). "truncated" is True when more than
        max_results paths matched the query.
        """
        if not self._path_search_lock.acquire(blocking=False):
            return [], True

        try:
            return self._rank_git_paths(cwd, keyword_norm, max_results=max_results)
        finally:
            self._path_search_lock.release()

    def _rank_git_paths(self, cwd: Path, keyword_norm: str, *, max_results: int) -> tuple[list[str], bool]:
        repo_root = self._get_git_repo_root(cwd)
        if repo_root is None:
            return [], False

        now = time.monotonic()
        git_cache_ttl = max(self._cache_ttl, 30.0)
        if (
            self._git_file_list is None
            or self._git_file_list_cwd != cwd
            or now - self._git_file_list_time > git_cache_ttl
        ):
            cmd = ["git", "-c", "core.quotePath=false", "ls-files", "-co", "--exclude-standard"]
            r = self._run_cmd(cmd, cwd=repo_root, timeout_sec=self._cmd_timeout_sec)
            if not r.ok:
                self._git_file_list = []
                self._git_dir_list = []
                self._git_file_list_time = now
                self._git_file_list_cwd = cwd
            else:
                all_lines = [self._decode_git_path_line(line) for line in r.lines]
                # Supplement with submodule contents: git ls-files -co doesn't
                # recurse into submodules (they appear as single gitlink entries).
                r_sub = self._run_cmd(
                    ["git", "-c", "core.quotePath=false", "ls-files", "--recurse-submodules"],
                    cwd=repo_root,
                    timeout_sec=self._cmd_timeout_sec,
                )
                if r_sub.ok:
                    main_set = set(all_lines)
                    all_lines.extend(
                        rel for line in r_sub.lines if (rel := self._decode_git_path_line(line)) not in main_set
                    )

                cwd_resolved = cwd.resolve()
                root_resolved = repo_root.resolve()
                files: list[str] = []
                directories: set[str] = set()
                for rel in all_lines:
                    abs_path = root_resolved / rel
                    try:
                        rel_to_cwd = abs_path.relative_to(cwd_resolved)
                    except ValueError:
                        continue
                    rel_posix = rel_to_cwd.as_posix()
                    files.append(rel_posix)
                    parent = os.path.dirname(rel_posix)
                    while parent and parent != ".":
                        directories.add(f"{parent}/")
                        parent = os.path.dirname(parent)
                self._git_file_list = files
                self._git_dir_list = sorted(directories)
                self._git_file_list_time = now
                self._git_file_list_cwd = cwd

        all_files = self._git_file_list or []
        all_directories = self._git_dir_list or []
        ranked: list[_RankedPath] = []
        truncated = False
        for paths in (all_directories, all_files):
            for path in paths:
                if _add_ranked_path(ranked, path, keyword_norm, limit=max_results):
                    truncated = True

        return [path for _, _, path in ranked], truncated

    def _decode_git_path_line(self, line: str) -> str:
        """Decode git's C-style quoted path output when core.quotePath is enabled."""

        if len(line) < 2 or not line.startswith('"') or not line.endswith('"'):
            return line

        inner = line[1:-1]
        out = bytearray()
        escapes = {
            "a": b"\a",
            "b": b"\b",
            "f": b"\f",
            "n": b"\n",
            "r": b"\r",
            "t": b"\t",
            "v": b"\v",
            "\\": b"\\",
            '"': b'"',
        }

        i = 0
        while i < len(inner):
            ch = inner[i]
            if ch != "\\":
                out.extend(ch.encode())
                i += 1
                continue

            i += 1
            if i >= len(inner):
                out.extend(b"\\")
                break

            esc = inner[i]
            if esc in escapes:
                out.extend(escapes[esc])
                i += 1
                continue

            if "0" <= esc <= "7":
                end = i + 1
                while end < min(i + 3, len(inner)) and "0" <= inner[end] <= "7":
                    end += 1
                out.append(int(inner[i:end], 8))
                i = end
                continue

            out.extend(esc.encode())
            i += 1

        try:
            return out.decode()
        except UnicodeDecodeError:
            return line

    def _get_git_repo_root(self, cwd: Path) -> Path | None:
        if not self._has_cmd("git"):
            return None

        now = time.monotonic()
        ttl = max(self._cache_ttl, 30.0)
        if self._git_repo_root_cwd == cwd and now - self._git_repo_root_time < ttl:
            return self._git_repo_root

        r = self._run_cmd(["git", "rev-parse", "--show-toplevel"], cwd=cwd, timeout_sec=0.5)
        root = Path(r.lines[0]) if r.ok and r.lines else None

        self._git_repo_root = root
        self._git_repo_root_time = now
        self._git_repo_root_cwd = cwd
        return root

    def _has_cmd(self, name: str) -> bool:
        return shutil.which(name) is not None

    def _suggest_for_empty_fragment(self, cwd: Path) -> list[str]:
        """Lightweight suggestions when user typed only '@': list cwd's children.

        Avoids running external tools; shows immediate directories first, then files.
        Filters out .git, .venv, and node_modules to reduce noise.
        Hidden files and paths containing "test" are deprioritized.
        """
        excluded = {".git", ".venv", "node_modules"}
        items: list[str] = []
        try:
            # Sort by: hidden files last, test paths last, directories first, then name
            def sort_key(p: Path) -> tuple[int, int, int, str]:
                name = p.name
                is_hidden = name.startswith(".")
                has_test = "test" in name.lower()
                is_file = not p.is_dir()
                return (1 if is_hidden else 0, 1 if has_test else 0, 1 if is_file else 0, name.lower())

            for p in sorted(cwd.iterdir(), key=sort_key):
                name = p.name
                if name in excluded:
                    continue
                rel = os.path.relpath(p, cwd)
                if p.is_dir() and not rel.endswith("/"):
                    rel += "/"
                items.append(rel)
        except OSError:
            return []
        return items[: min(self._max_results, 100)]

    def _run_cmd(self, cmd: list[str], cwd: Path | None = None, *, timeout_sec: float) -> _CmdResult:
        cmd_str = " ".join(cmd)
        start = time.monotonic()
        try:
            p = subprocess.run(
                cmd,
                cwd=str(cwd) if cwd else None,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=timeout_sec,
            )
            elapsed_ms = (time.monotonic() - start) * 1000
            if p.returncode == 0:
                lines = [ln.strip() for ln in p.stdout.splitlines() if ln.strip()]
                log_debug(
                    f"[completer] cmd={cmd_str} elapsed={elapsed_ms:.1f}ms results={len(lines)}",
                    debug_type=DebugType.EXECUTION,
                )
                return _CmdResult(True, lines)
            log_debug(
                f"[completer] cmd={cmd_str} elapsed={elapsed_ms:.1f}ms returncode={p.returncode}",
                debug_type=DebugType.EXECUTION,
            )
            return _CmdResult(False, [])
        except Exception as e:
            elapsed_ms = (time.monotonic() - start) * 1000
            log_debug(
                f"[completer] cmd={cmd_str} elapsed={elapsed_ms:.1f}ms error={e!r}",
                debug_type=DebugType.EXECUTION,
            )
            return _CmdResult(False, [])
