"""REPL completion handlers for @ file paths, / slash commands, and $ skills.

This module provides completers for the REPL input:
- _SlashCommandCompleter: Completes slash commands on the first line
- _SkillCompleter: Completes skill names on the first line with $ prefix
- _AtFilesCompleter: Completes @path segments using fd or ripgrep
- _ComboCompleter: Combines all completers with priority logic

Public API:
- create_repl_completer(): Factory function to create the combined completer
- AT_TOKEN_PATTERN: Regex pattern for @token matching (used by key bindings)
- SKILL_TOKEN_PATTERN: Regex pattern for $skill matching (used by key bindings)
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import NamedTuple

from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.document import Document
from prompt_toolkit.formatted_text import FormattedText

from klaude_code.protocol.commands import CommandInfo
from klaude_code.trace.log import DebugType, log_debug

# Pattern to match @token for completion refresh (used by key bindings).
# Supports both plain tokens like `@src/file.py` and quoted tokens like
# `@"path with spaces/file.py"` so that filenames with spaces remain a
# single logical token.
AT_TOKEN_PATTERN = re.compile(r'(^|\s)@(?P<frag>"[^"]*"|[^\s]*)$')

# Pattern to match $skill or ¥skill token for skill completion (used by key bindings).
SKILL_TOKEN_PATTERN = re.compile(r"^[$¥](?P<frag>\S*)$")


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


class _SlashCommandCompleter(Completer):
    """Complete slash commands at the beginning of the first line.

    Behavior:
    - Only triggers when cursor is on first line and text matches /...
    - Shows available slash commands with descriptions
    - Inserts trailing space after completion
    """

    _SLASH_TOKEN_RE = re.compile(r"^/(?P<frag>\S*)$")

    def __init__(self, command_info_provider: Callable[[], list[CommandInfo]] | None = None) -> None:
        self._command_info_provider = command_info_provider

    def get_completions(
        self,
        document: Document,
        complete_event,  # type: ignore[override]
    ) -> Iterable[Completion]:
        # Only complete on first line
        if document.cursor_position_row != 0:
            return

        if self._command_info_provider is None:
            return

        text_before = document.current_line_before_cursor
        m = self._SLASH_TOKEN_RE.search(text_before)
        if not m:
            return

        frag = m.group("frag")
        token_start = len(text_before) - len(f"/{frag}")
        start_position = token_start - len(text_before)  # negative offset

        # Get available commands from provider
        command_infos = self._command_info_provider()

        # Filter commands that match the fragment (preserve registration order)
        matched: list[tuple[str, CommandInfo, str]] = []
        for cmd_info in command_infos:
            if cmd_info.name.startswith(frag):
                hint = f" [{cmd_info.placeholder}]" if cmd_info.support_addition_params else ""
                matched.append((cmd_info.name, cmd_info, hint))

        if not matched:
            return

        for cmd_name, cmd_info, hint in matched:
            completion_text = f"/{cmd_name} "
            # Use FormattedText to style the hint (placeholder) in bright black
            display = FormattedText([("", cmd_name), ("ansibrightblack", hint)]) if hint else cmd_name
            yield Completion(
                text=completion_text,
                start_position=start_position,
                display=display,
                display_meta=cmd_info.summary,
            )

    def is_slash_command_context(self, document: Document) -> bool:
        """Check if current context is a slash command."""
        if document.cursor_position_row != 0:
            return False
        text_before = document.current_line_before_cursor
        return bool(self._SLASH_TOKEN_RE.search(text_before))


class _SkillCompleter(Completer):
    """Complete skill names at the beginning of the first line.

    Behavior:
    - Only triggers when cursor is on first line and text matches $ or ¥...
    - Shows available skills with descriptions
    - Inserts trailing space after completion
    """

    _SKILL_TOKEN_RE = SKILL_TOKEN_PATTERN

    def get_completions(
        self,
        document: Document,
        complete_event,  # type: ignore[override]
    ) -> Iterable[Completion]:
        # Only complete on first line
        if document.cursor_position_row != 0:
            return

        text_before = document.current_line_before_cursor
        m = self._SKILL_TOKEN_RE.search(text_before)
        if not m:
            return

        frag = m.group("frag").lower()
        # Get the prefix character ($ or ¥)
        prefix_char = text_before[0]
        token_start = len(text_before) - len(f"{prefix_char}{m.group('frag')}")
        start_position = token_start - len(text_before)  # negative offset

        # Get available skills from SkillTool
        skills = self._get_available_skills()
        if not skills:
            return

        # Filter skills that match the fragment (case-insensitive)
        matched: list[tuple[str, str, str]] = []  # (name, description, location)
        for name, desc, location in skills:
            if frag in name.lower() or frag in desc.lower():
                matched.append((name, desc, location))

        if not matched:
            return

        # Calculate max location length for alignment
        max_loc_len = max(len(loc) for _, _, loc in matched)

        for name, desc, location in matched:
            completion_text = f"${name} "
            # Pad location to align descriptions
            padded_location = f"[{location}]".ljust(max_loc_len + 2)  # +2 for brackets
            yield Completion(
                text=completion_text,
                start_position=start_position,
                display=name,
                display_meta=f"{padded_location} {desc}",
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
        if document.cursor_position_row != 0:
            return False
        text_before = document.current_line_before_cursor
        return bool(self._SKILL_TOKEN_RE.search(text_before))


class _ComboCompleter(Completer):
    """Combined completer that handles @ file paths, / slash commands, and $ skills."""

    def __init__(self, command_info_provider: Callable[[], list[CommandInfo]] | None = None) -> None:
        self._at_completer = _AtFilesCompleter()
        self._slash_completer = _SlashCommandCompleter(command_info_provider=command_info_provider)
        self._skill_completer = _SkillCompleter()

    def get_completions(
        self,
        document: Document,
        complete_event,  # type: ignore[override]
    ) -> Iterable[Completion]:
        # Try slash command completion first (only on first line)
        if document.cursor_position_row == 0 and self._slash_completer.is_slash_command_context(document):
            yield from self._slash_completer.get_completions(document, complete_event)
            return

        # Try skill completion (only on first line with $ prefix)
        if document.cursor_position_row == 0 and self._skill_completer.is_skill_context(document):
            yield from self._skill_completer.get_completions(document, complete_event)
            return

        # Fall back to @ file completion
        yield from self._at_completer.get_completions(document, complete_event)


class _AtFilesCompleter(Completer):
    """Complete @path segments using fd or ripgrep.

    Behavior:
    - Only triggers when the cursor is after an "@..." token (until whitespace).
    - Completes paths relative to the current working directory.
    - Uses `fd` when available (files and directories), falls back to `rg --files` (files only).
    - Debounces external commands and caches results to avoid excessive spawning.
    - Inserts a trailing space after completion to stop further triggering.
    """

    _AT_TOKEN_RE = AT_TOKEN_PATTERN

    def __init__(
        self,
        debounce_sec: float = 0.25,
        cache_ttl_sec: float = 60.0,
        max_results: int = 20,
    ):
        self._debounce_sec = debounce_sec
        self._cache_ttl = cache_ttl_sec
        self._max_results = max_results

        # Debounce/caching state
        self._last_cmd_time: float = 0.0
        self._last_query_key: str | None = None
        self._last_results: list[str] = []
        self._last_results_time: float = 0.0
        self._last_results_truncated: bool = False

        # rg --files cache (used when fd is unavailable)
        self._rg_file_list: list[str] | None = None
        self._rg_file_list_time: float = 0.0
        self._rg_file_list_cwd: Path | None = None

        # git ls-files cache (preferred when inside a git repo)
        self._git_repo_root: Path | None = None
        self._git_repo_root_time: float = 0.0
        self._git_repo_root_cwd: Path | None = None

        self._git_file_list: list[str] | None = None
        self._git_file_list_lower: list[str] | None = None
        self._git_file_list_time: float = 0.0
        self._git_file_list_cwd: Path | None = None

        # Command timeout is intentionally higher than a keypress cadence.
        # We rely on caching/narrowing to avoid calling fd repeatedly.
        self._cmd_timeout_sec: float = 3.0

    # ---- prompt_toolkit API ----
    def get_completions(self, document: Document, complete_event) -> Iterable[Completion]:  # type: ignore[override]
        text_before = document.text_before_cursor
        m = self._AT_TOKEN_RE.search(text_before)
        if not m:
            return []  # type: ignore[reportUnknownVariableType]

        frag = m.group("frag")  # raw text after '@' and before cursor (may be quoted)
        # Normalize fragment for search: support optional quoting syntax @"...".
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
                    display=self._format_display_label(s, 0),
                    display_meta=s,
                )
            return []  # type: ignore[reportUnknownVariableType]

        # Gather suggestions with debounce/caching based on search keyword
        suggestions = self._complete_paths(cwd, search_frag)
        if not suggestions:
            return []  # type: ignore[reportUnknownVariableType]

        # Prepare Completion objects. Replace from the '@' character.
        start_position = token_start_in_input - len(text_before)  # negative
        for s in suggestions[: self._max_results]:
            # Insert formatted text (with quoting when needed) so that subsequent typing does not keep triggering
            yield Completion(
                text=self._format_completion_text(s, is_quoted=is_quoted),
                start_position=start_position,
                display=self._format_display_label(s, 0),
                display_meta=s,
            )

    # ---- Core logic ----
    def _complete_paths(self, cwd: Path, keyword: str) -> list[str]:
        now = time.monotonic()
        key_norm = keyword.lower()
        query_key = f"{cwd.resolve()}::search::{key_norm}"

        max_scan_results = self._max_results * 3

        # Debounce: if called too soon again, filter last results
        if self._last_results and self._last_query_key is not None:
            prev = self._last_query_key
            if self._same_scope(prev, query_key):
                # Determine if query is narrowing or broadening
                _, prev_kw = self._parse_query_key(prev)
                _, cur_kw = self._parse_query_key(query_key)
                is_narrowing = (
                    prev_kw is not None
                    and cur_kw is not None
                    and len(cur_kw) >= len(prev_kw)
                    and cur_kw.startswith(prev_kw)
                )

                # If the previous result set was not truncated, it is a complete
                # superset for any narrower prefix. Reuse it even if the user
                # pauses between keystrokes.
                if (
                    is_narrowing
                    and not self._last_results_truncated
                    and now - self._last_results_time < self._cache_ttl
                ):
                    return self._filter_and_format(self._last_results, cwd, key_norm)

                if is_narrowing and (now - self._last_cmd_time) < self._debounce_sec:
                    # For rapid narrowing, fast-filter previous results to avoid expensive calls
                    # If the previous result set was truncated (e.g., for a 1-char query),
                    # filtering it can legitimately produce an empty set even when matches
                    # exist elsewhere. Fall back to a real search in that case.
                    filtered = self._filter_and_format(self._last_results, cwd, key_norm)
                    if filtered:
                        return filtered

        # Cache TTL: reuse cached results for same query within TTL
        if self._last_results and self._last_query_key == query_key and now - self._last_results_time < self._cache_ttl:
            return self._filter_and_format(self._last_results, cwd, key_norm)

        # Prefer git index (fast in large repos), then fd, then rg --files.
        results: list[str] = []
        truncated = False

        # For very short keywords, prefer fd's early-exit behavior.
        # For keywords >= 2 chars, using git's file list is typically faster
        # than scanning the filesystem repeatedly.
        if len(key_norm) >= 2:
            results, truncated = self._git_paths_for_keyword(cwd, key_norm, max_results=max_scan_results)

        if not results:
            if self._has_cmd("fd"):
                # First, get immediate children matching the keyword (depth=0).
                # fd's traversal order is not depth-first, so --max-results may
                # truncate shallow matches. We ensure depth=0 items are always included.
                immediate = self._get_immediate_matches(cwd, key_norm)
                # Use fd to search anywhere in full path (files and directories), case-insensitive
                fd_results, truncated = self._run_fd_search(cwd, key_norm, max_results=max_scan_results)
                # Merge: immediate matches first, then fd results (deduped in _filter_and_format)
                results = immediate + fd_results
            elif self._has_cmd("rg"):
                # Use rg to search only in current directory
                rg_cache_ttl = max(self._cache_ttl, 30.0)
                if (
                    self._rg_file_list is None
                    or self._rg_file_list_cwd != cwd
                    or now - self._rg_file_list_time > rg_cache_ttl
                ):
                    cmd = [
                        "rg",
                        "--files",
                        "--hidden",
                        "--glob",
                        "!**/.git/**",
                        "--glob",
                        "!**/.venv/**",
                        "--glob",
                        "!**/node_modules/**",
                    ]
                    r = self._run_cmd(cmd, cwd=cwd, timeout_sec=self._cmd_timeout_sec)  # Search from current directory
                    if r.ok:
                        self._rg_file_list = r.lines
                        self._rg_file_list_time = now
                        self._rg_file_list_cwd = cwd
                    else:
                        self._rg_file_list = []
                        self._rg_file_list_time = now
                        self._rg_file_list_cwd = cwd
                # Filter by keyword
                all_files = self._rg_file_list or []
                kn = key_norm
                results = [p for p in all_files if kn in p.lower()]
                # For rg fallback, we don't implement any priority sorting.
            else:
                return []

        # Update caches
        self._last_cmd_time = now
        self._last_query_key = query_key
        self._last_results = results
        self._last_results_time = now
        self._last_results_truncated = truncated
        return self._filter_and_format(results, cwd, key_norm)

    def _filter_and_format(
        self,
        paths_from_root: list[str],
        cwd: Path,
        keyword_norm: str,
    ) -> list[str]:
        # Filter to keyword (case-insensitive) and rank by:
        # 1. Hidden files (starting with .) are deprioritized
        # 2. Paths containing "test" are deprioritized
        # 3. Directory depth (shallower first)
        # 4. Basename hit first, then path hit position, then length
        # Since both fd and rg now search from current directory, all paths are relative to cwd
        kn = keyword_norm
        out: list[tuple[str, tuple[int, int, int, int, int, int, int]]] = []
        for p in paths_from_root:
            pl = p.lower()
            if kn not in pl:
                continue

            # Most tools return paths relative to cwd. Some include a leading
            # './' prefix; strip that exact prefix only.
            #
            # Do not use lstrip('./') here: it would also remove the leading '.'
            # from dotfiles/directories like '.claude/'.
            rel_to_cwd = p.removeprefix("./").removeprefix(".\\")
            base = os.path.basename(rel_to_cwd.rstrip("/")).lower()
            base_pos = base.find(kn)
            path_pos = pl.find(kn)
            depth = rel_to_cwd.rstrip("/").count("/")

            # Deprioritize hidden files/directories (any path segment starting with .)
            is_hidden = any(seg.startswith(".") for seg in rel_to_cwd.split("/") if seg)
            # Deprioritize paths containing "test"
            has_test = "test" in pl

            score = (
                1 if is_hidden else 0,
                1 if has_test else 0,
                depth,
                0 if base_pos != -1 else 1,
                base_pos if base_pos != -1 else 10_000,
                path_pos,
                len(p),
            )

            out.append((rel_to_cwd, score))
        # Sort by score
        out.sort(key=lambda x: x[1])
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

    def _format_display_label(self, suggestion: str, align_width: int) -> str:
        """Format visible label for a completion option.

        Keep this unstyled so that the completion menu's selection style can
        fully override the selected row.
        """

        _ = align_width
        return self._display_name(suggestion)

    def _display_align_width(self, suggestions: list[str]) -> int:
        """Calculate alignment width for display labels."""

        return max((len(self._display_name(s)) for s in suggestions), default=0)

    def _display_name(self, suggestion: str) -> str:
        """Return the basename (with trailing slash for directories) for display."""

        if not suggestion:
            return suggestion

        is_dir = suggestion.endswith("/")
        stripped = suggestion.rstrip("/")
        base = stripped.split("/")[-1] if stripped else suggestion
        if is_dir:
            return f"{base}/"
        return base

    def _same_scope(self, prev_key: str, cur_key: str) -> bool:
        # Consider same scope if they share the same base directory and one prefix startswith the other
        try:
            prev_root, prev_pref = prev_key.split("::", 1)
            cur_root, cur_pref = cur_key.split("::", 1)
        except ValueError:
            return False
        return prev_root == cur_root and (prev_pref.startswith(cur_pref) or cur_pref.startswith(prev_pref))

    def _parse_query_key(self, key: str) -> tuple[str | None, str | None]:
        try:
            root, rest = key.split("::", 1)
            tag, kw = rest.split("::", 1)
            if tag != "search":
                return root, None
            return root, kw
        except ValueError:
            return None, None

    # ---- Utilities ----
    def _run_fd_search(self, cwd: Path, keyword_norm: str, *, max_results: int) -> tuple[list[str], bool]:
        """Run fd search and return (results, truncated).

        Note: This is called in the prompt_toolkit completion path, so avoid
        doing extra background scans here.
        """
        cmd = [
            "fd",
            "--color=never",
            "--type",
            "f",
            "--type",
            "d",
            "--hidden",
            "--full-path",
            "-i",
            "-F",
            "--max-results",
            str(max_results),
            "--exclude",
            ".git",
            "--exclude",
            ".venv",
            "--exclude",
            "node_modules",
            keyword_norm,
            ".",
        ]

        r = self._run_cmd(cmd, cwd=cwd, timeout_sec=self._cmd_timeout_sec)
        lines = r.lines if r.ok else []
        return lines, (len(lines) >= max_results)

    def _git_paths_for_keyword(self, cwd: Path, keyword_norm: str, *, max_results: int) -> tuple[list[str], bool]:
        """Get path suggestions from the git index (fast for large repos).

        Returns (candidates, truncated). "truncated" is True when we
        intentionally stop early to keep per-keystroke costs bounded.
        """
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
            cmd = ["git", "ls-files", "-co", "--exclude-standard"]
            r = self._run_cmd(cmd, cwd=repo_root, timeout_sec=self._cmd_timeout_sec)
            if not r.ok:
                self._git_file_list = []
                self._git_file_list_lower = []
                self._git_file_list_time = now
                self._git_file_list_cwd = cwd
            else:
                cwd_resolved = cwd.resolve()
                root_resolved = repo_root.resolve()
                files: list[str] = []
                files_lower: list[str] = []
                for rel in r.lines:
                    abs_path = root_resolved / rel
                    try:
                        rel_to_cwd = abs_path.relative_to(cwd_resolved)
                    except ValueError:
                        continue
                    rel_posix = rel_to_cwd.as_posix()
                    files.append(rel_posix)
                    files_lower.append(rel_posix.lower())
                self._git_file_list = files
                self._git_file_list_lower = files_lower
                self._git_file_list_time = now
                self._git_file_list_cwd = cwd

        all_files = self._git_file_list or []
        all_files_lower = self._git_file_list_lower or []
        kn = keyword_norm

        # Bound per-keystroke work: stop scanning once enough matches are found.
        matching_files: list[str] = []
        scan_truncated = False
        for p, pl in zip(all_files, all_files_lower, strict=False):
            if kn in pl:
                matching_files.append(p)
                if len(matching_files) >= max_results:
                    scan_truncated = True
                    break

        # Also include parent directories of matching files so users can
        # complete into a folder, similar to fd's directory results.
        dir_candidates: set[str] = set()
        for p in matching_files[: max_results * 3]:
            parent = os.path.dirname(p)
            while parent and parent != ".":
                dir_candidates.add(f"{parent}/")
                parent = os.path.dirname(parent)

        dir_list = sorted(dir_candidates)
        dir_truncated = False
        if len(dir_list) > max_results:
            dir_list = dir_list[:max_results]
            dir_truncated = True

        candidates = matching_files + dir_list
        truncated = scan_truncated or dir_truncated
        return candidates, truncated

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

    def _get_immediate_matches(self, cwd: Path, keyword_norm: str) -> list[str]:
        """Get immediate children of cwd that match the keyword (case-insensitive).

        This ensures depth=0 matches are always included, even when fd's
        --max-results truncates before reaching them.
        """
        excluded = {".git", ".venv", "node_modules"}
        items: list[str] = []
        try:
            for p in cwd.iterdir():
                name = p.name
                if name in excluded:
                    continue
                if keyword_norm in name.lower():
                    rel = name
                    if p.is_dir():
                        rel += "/"
                    items.append(rel)
        except OSError:
            return []
        return items

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
