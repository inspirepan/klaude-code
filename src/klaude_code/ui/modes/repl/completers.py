"""REPL completion handlers for @ file paths and / slash commands.

This module provides completers for the REPL input:
- _SlashCommandCompleter: Completes slash commands on the first line
- _AtFilesCompleter: Completes @path segments using fd or ripgrep
- _ComboCompleter: Combines both completers with priority logic

Public API:
- create_repl_completer(): Factory function to create the combined completer
- AT_TOKEN_PATTERN: Regex pattern for @token matching (used by key bindings)
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from collections.abc import Iterable
from pathlib import Path
from typing import NamedTuple

from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.document import Document
from prompt_toolkit.formatted_text import HTML

from klaude_code.command import get_commands
from klaude_code.trace.log import DebugType, log_debug

# Pattern to match @token for completion refresh (used by key bindings).
# Supports both plain tokens like `@src/file.py` and quoted tokens like
# `@"path with spaces/file.py"` so that filenames with spaces remain a
# single logical token.
AT_TOKEN_PATTERN = re.compile(r'(^|\s)@(?P<frag>"[^"]*"|[^\s]*)$')


def create_repl_completer() -> Completer:
    """Create and return the combined REPL completer.

    Returns a completer that handles both @ file paths and / slash commands.
    """
    return _ComboCompleter()


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

    def get_completions(
        self,
        document: Document,
        complete_event,  # type: ignore[override]
    ) -> Iterable[Completion]:
        # Only complete on first line
        if document.cursor_position_row != 0:
            return

        text_before = document.current_line_before_cursor
        m = self._SLASH_TOKEN_RE.search(text_before)
        if not m:
            return

        frag = m.group("frag")
        token_start = len(text_before) - len(f"/{frag}")
        start_position = token_start - len(text_before)  # negative offset

        # Get available commands
        commands = get_commands()

        # Filter commands that match the fragment (preserve registration order)
        matched: list[tuple[str, object, str]] = []
        for cmd_name, cmd_obj in commands.items():
            if cmd_name.startswith(frag):
                hint = f" [{cmd_obj.placeholder}]" if cmd_obj.support_addition_params else ""
                matched.append((cmd_name, cmd_obj, hint))

        if not matched:
            return

        # Calculate max width for alignment
        # Find the longest command+hint length
        max_len = max(len(name) + len(hint) for name, _, hint in matched)
        # Set a minimum width (e.g. 20) and add some padding
        align_width = max(max_len, 20) + 2

        for cmd_name, cmd_obj, hint in matched:
            label_len = len(cmd_name) + len(hint)
            padding = " " * (align_width - label_len)

            # Using HTML for formatting: bold command name, normal hint, gray summary
            display_text = HTML(
                f"<b>{cmd_name}</b>{hint}{padding}<style color='ansibrightblack'>{cmd_obj.summary}</style>"  # pyright: ignore[reportUnknownMemberType, reportAttributeAccessIssue]
            )
            completion_text = f"/{cmd_name} "
            yield Completion(
                text=completion_text,
                start_position=start_position,
                display=display_text,
            )

    def is_slash_command_context(self, document: Document) -> bool:
        """Check if current context is a slash command."""
        if document.cursor_position_row != 0:
            return False
        text_before = document.current_line_before_cursor
        return bool(self._SLASH_TOKEN_RE.search(text_before))


class _ComboCompleter(Completer):
    """Combined completer that handles both @ file paths and / slash commands."""

    def __init__(self) -> None:
        self._at_completer = _AtFilesCompleter()
        self._slash_completer = _SlashCommandCompleter()

    def get_completions(
        self,
        document: Document,
        complete_event,  # type: ignore[override]
    ) -> Iterable[Completion]:
        # Try slash command completion first (only on first line)
        if document.cursor_position_row == 0 and self._slash_completer.is_slash_command_context(document):
            yield from self._slash_completer.get_completions(document, complete_event)
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
        cache_ttl_sec: float = 10.0,
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

        # rg --files cache (used when fd is unavailable)
        self._rg_file_list: list[str] | None = None
        self._rg_file_list_time: float = 0.0

        # Cache for ignored paths (gitignored files)
        self._last_ignored_paths: set[str] = set()

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
                    display=s,
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
                display=s,
            )

    # ---- Core logic ----
    def _complete_paths(self, cwd: Path, keyword: str) -> list[str]:
        now = time.monotonic()
        key_norm = keyword.lower()
        query_key = f"{cwd.resolve()}::search::{key_norm}"

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
                if is_narrowing and (now - self._last_cmd_time) < self._debounce_sec:
                    # For narrowing, fast-filter previous results to avoid expensive calls
                    return self._filter_and_format(self._last_results, cwd, key_norm, self._last_ignored_paths)

        # Cache TTL: reuse cached results for same query within TTL
        if self._last_results and self._last_query_key == query_key and now - self._last_results_time < self._cache_ttl:
            return self._filter_and_format(self._last_results, cwd, key_norm, self._last_ignored_paths)

        # Prefer fd; otherwise fallback to rg --files
        results: list[str] = []
        ignored_paths: set[str] = set()
        if self._has_cmd("fd"):
            # Use fd to search anywhere in full path (files and directories), case-insensitive
            results, ignored_paths = self._run_fd_search(cwd, key_norm)
        elif self._has_cmd("rg"):
            # Use rg to search only in current directory
            if self._rg_file_list is None or now - self._rg_file_list_time > max(self._cache_ttl, 30.0):
                cmd = ["rg", "--files", "--no-ignore", "--hidden"]
                r = self._run_cmd(cmd, cwd=cwd)  # Search from current directory
                if r.ok:
                    self._rg_file_list = r.lines
                    self._rg_file_list_time = now
                else:
                    self._rg_file_list = []
                    self._rg_file_list_time = now
            # Filter by keyword
            all_files = self._rg_file_list or []
            kn = key_norm
            results = [p for p in all_files if kn in p.lower()]
            # For rg fallback, we don't distinguish ignored files (no priority sorting)
        else:
            return []

        # Update caches
        self._last_cmd_time = now
        self._last_query_key = query_key
        self._last_results = results
        self._last_results_time = now
        self._last_ignored_paths = ignored_paths
        return self._filter_and_format(results, cwd, key_norm, ignored_paths)

    def _filter_and_format(
        self,
        paths_from_root: list[str],
        cwd: Path,
        keyword_norm: str,
        ignored_paths: set[str] | None = None,
    ) -> list[str]:
        # Filter to keyword (case-insensitive) and rank by:
        # 1. Non-gitignored files first (is_ignored: 0 or 1)
        # 2. Basename hit first, then path hit position, then length
        # Since both fd and rg now search from current directory, all paths are relative to cwd
        kn = keyword_norm
        ignored_paths = ignored_paths or set()
        out: list[tuple[str, tuple[int, int, int, int, int]]] = []
        for p in paths_from_root:
            pl = p.lower()
            if kn not in pl:
                continue

            # Use path directly since it's already relative to current directory
            rel_to_cwd = p.lstrip("./")
            base = os.path.basename(p).lower()
            base_pos = base.find(kn)
            path_pos = pl.find(kn)
            # Check if this path is in the ignored set (gitignored files)
            is_ignored = 1 if rel_to_cwd in ignored_paths else 0
            score = (
                is_ignored,
                0 if base_pos != -1 else 1,
                base_pos if base_pos != -1 else 10_000,
                path_pos,
                len(p),
            )

            # Append trailing slash for directories
            full_path = cwd / rel_to_cwd
            if full_path.is_dir() and not rel_to_cwd.endswith("/"):
                rel_to_cwd = rel_to_cwd + "/"
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
        except Exception:
            return None, None

    # ---- Utilities ----
    def _run_fd_search(self, cwd: Path, keyword_norm: str) -> tuple[list[str], set[str]]:
        """Run fd search and return (all_results, ignored_paths).

        First runs fd without --no-ignore to get tracked files,
        then runs with --no-ignore to get all files including gitignored ones.
        Returns the combined results and a set of paths that are gitignored.
        """
        pattern = self._escape_regex(keyword_norm)
        base_cmd = [
            "fd",
            "--color=never",
            "--type",
            "f",
            "--type",
            "d",
            "--hidden",
            "--full-path",
            "-i",
            "--max-results",
            str(self._max_results * 3),
            "--exclude",
            ".git",
            "--exclude",
            ".venv",
            "--exclude",
            "node_modules",
            pattern,
            ".",
        ]

        # First run: get tracked (non-ignored) files
        r_tracked = self._run_cmd(base_cmd, cwd=cwd)
        tracked_paths: set[str] = set(p.lstrip("./") for p in r_tracked.lines) if r_tracked.ok else set()

        # Second run: get all files including ignored ones
        cmd_all = base_cmd.copy()
        cmd_all.insert(2, "--no-ignore")  # Insert after --color=never
        r_all = self._run_cmd(cmd_all, cwd=cwd)
        all_paths = r_all.lines if r_all.ok else []

        # Calculate which paths are gitignored (in all but not in tracked)
        ignored_paths = set(p.lstrip("./") for p in all_paths) - tracked_paths

        return all_paths, ignored_paths

    def _escape_regex(self, s: str) -> str:
        # Escape for fd (regex by default). Keep '/' as is for path boundaries.
        return re.escape(s).replace("/", "/")

    def _has_cmd(self, name: str) -> bool:
        return shutil.which(name) is not None

    def _suggest_for_empty_fragment(self, cwd: Path) -> list[str]:
        """Lightweight suggestions when user typed only '@': list cwd's children.

        Avoids running external tools; shows immediate directories first, then files.
        Filters out .git, .venv, and node_modules to reduce noise.
        """
        excluded = {".git", ".venv", "node_modules"}
        items: list[str] = []
        try:
            for p in sorted(cwd.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
                name = p.name
                if name in excluded:
                    continue
                rel = os.path.relpath(p, cwd)
                if p.is_dir() and not rel.endswith("/"):
                    rel += "/"
                items.append(rel)
        except Exception:
            return []
        return items[: min(self._max_results, 100)]

    def _run_cmd(self, cmd: list[str], cwd: Path | None = None) -> _CmdResult:
        cmd_str = " ".join(cmd)
        start = time.monotonic()
        try:
            p = subprocess.run(
                cmd,
                cwd=str(cwd) if cwd else None,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=1.5,
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
