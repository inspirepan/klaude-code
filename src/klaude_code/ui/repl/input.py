from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
import uuid
from collections.abc import AsyncIterator, Callable, Iterable
from pathlib import Path
from typing import NamedTuple, cast, override

from PIL import Image, ImageGrab
from prompt_toolkit import PromptSession
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.completion import Completer, Completion, ThreadedCompleter
from prompt_toolkit.document import Document
from prompt_toolkit.filters import Condition
from prompt_toolkit.formatted_text import HTML, FormattedText
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.patch_stdout import patch_stdout
from prompt_toolkit.styles import Style

from klaude_code.command import get_commands
from klaude_code.core.clipboard_manifest import (
    CLIPBOARD_IMAGES_DIR,
    ClipboardManifest,
    ClipboardManifestEntry,
    next_session_token,
    persist_clipboard_manifest,
)
from klaude_code.ui.base.input_abc import InputProviderABC
from klaude_code.ui.base.utils import get_current_git_branch, show_path_with_tilde


class REPLStatusSnapshot(NamedTuple):
    """Snapshot of REPL status for bottom toolbar display."""

    model_name: str
    context_usage_percent: float | None
    llm_calls: int
    tool_calls: int
    update_message: str | None = None


kb = KeyBindings()

COMPLETION_SELECTED = "#5869f7"
COMPLETION_MENU = "ansibrightblack"
INPUT_PROMPT_STYLE = "ansimagenta"


class ClipboardCaptureState:
    def __init__(self, images_dir: Path | None = None, session_token: str | None = None):
        self._images_dir = images_dir or CLIPBOARD_IMAGES_DIR
        self._session_token = session_token or next_session_token()
        self._pending: list[ClipboardManifestEntry] = []
        self._counter = 1

    def capture_from_clipboard(self) -> str | None:
        try:
            clipboard_data = ImageGrab.grabclipboard()
        except Exception:
            return None
        if not isinstance(clipboard_data, Image.Image):
            return None
        try:
            self._images_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            return None
        filename = f"clipboard_{uuid.uuid4().hex[:8]}.png"
        path = self._images_dir / filename
        try:
            clipboard_data.save(path, "PNG")
        except Exception:
            return None
        tag = f"[Image #{self._counter}]"
        self._counter += 1
        saved_entry = ClipboardManifestEntry(tag=tag, path=str(path), saved_at_ts=time.time())
        self._pending.append(saved_entry)
        return tag

    def flush_manifest(self) -> ClipboardManifest | None:
        if not self._pending:
            return None
        manifest = ClipboardManifest(
            entries=list(self._pending),
            created_at_ts=time.time(),
            source_id=self._session_token,
        )
        self._pending = []
        self._counter = 1
        return manifest


_clipboard_state = ClipboardCaptureState()


@kb.add("c-v")
def _(event):  # type: ignore
    """Paste image from clipboard as [Image #N]."""
    tag = _clipboard_state.capture_from_clipboard()
    if tag:
        try:
            event.current_buffer.insert_text(tag)  # pyright: ignore[reportUnknownMemberType]
        except Exception:
            pass


@kb.add("enter")
def _(event):  # type: ignore
    buf = event.current_buffer  # type: ignore
    doc = buf.document  # type: ignore

    # If VS Code/Windsurf/Cursor sent a "\\" sentinel before Enter (Shift+Enter mapping),
    # treat it as a request for a newline instead of submit.
    # This allows Shift+Enter to insert a newline in our multiline prompt.
    try:
        if doc.text_before_cursor.endswith("\\"):  # type: ignore[reportUnknownMemberType]
            buf.delete_before_cursor()  # remove the sentinel backslash  # type: ignore[reportUnknownMemberType]
            buf.insert_text("\n")  # type: ignore[reportUnknownMemberType]
            return
    except Exception:
        # Fall through to default behavior if anything goes wrong
        pass

    # If the entire buffer is whitespace-only, insert a newline rather than submitting.
    if len(buf.text.strip()) == 0:  # type: ignore
        buf.insert_text("\n")  # type: ignore
        return

    manifest = _clipboard_state.flush_manifest()
    if manifest:
        try:
            persist_clipboard_manifest(manifest)
        except Exception:
            pass

    buf.validate_and_handle()  # type: ignore


@kb.add("c-j")
def _(event):  # type: ignore
    event.current_buffer.insert_text("\n")  # type: ignore


@kb.add("c")
def _(event):  # type: ignore
    """Copy selected text to system clipboard, or insert 'c' if no selection."""
    buf = event.current_buffer  # type: ignore
    if buf.selection_state:  # type: ignore[reportUnknownMemberType]
        doc = buf.document  # type: ignore[reportUnknownMemberType]
        start, end = doc.selection_range()  # type: ignore[reportUnknownMemberType]
        selected_text: str = doc.text[start:end]  # type: ignore[reportUnknownMemberType]

        if selected_text:
            _copy_to_clipboard(selected_text)  # type: ignore[reportUnknownArgumentType]
        buf.exit_selection()  # type: ignore[reportUnknownMemberType]
    else:
        buf.insert_text("c")  # type: ignore[reportUnknownMemberType]


def _copy_to_clipboard(text: str) -> None:
    """Copy text to system clipboard using platform-specific commands."""
    import sys

    try:
        if sys.platform == "darwin":
            subprocess.run(["pbcopy"], input=text.encode("utf-8"), check=True)
        elif sys.platform == "win32":
            subprocess.run(["clip"], input=text.encode("utf-16"), check=True)
        else:
            # Linux: try xclip first, then xsel
            if shutil.which("xclip"):
                subprocess.run(["xclip", "-selection", "clipboard"], input=text.encode("utf-8"), check=True)
            elif shutil.which("xsel"):
                subprocess.run(["xsel", "--clipboard", "--input"], input=text.encode("utf-8"), check=True)
    except Exception:
        pass


@kb.add("backspace")
def _(event):  # type: ignore
    """Ensure completions refresh on backspace when editing an @token.

    We delete the character before cursor (default behavior), then explicitly
    trigger completion refresh if the caret is still within an @... token.
    """
    buf = event.current_buffer  # type: ignore
    # Handle selection: cut selection if present, otherwise delete one character
    if buf.selection_state:  # type: ignore[reportUnknownMemberType]
        buf.cut_selection()  # type: ignore[reportUnknownMemberType]
    else:
        buf.delete_before_cursor()  # type: ignore[reportUnknownMemberType]
    # If the token pattern still applies, refresh completion popup
    try:
        text_before = buf.document.text_before_cursor  # type: ignore[reportUnknownMemberType, reportUnknownVariableType]
        # Check for both @ tokens and / tokens (slash commands on first line only)
        should_refresh = False
        if _AtFilesCompleter._AT_TOKEN_RE.search(text_before):  # type: ignore[reportPrivateUsage, reportUnknownArgumentType]
            should_refresh = True
        elif buf.document.cursor_position_row == 0:  # type: ignore[reportUnknownMemberType]
            # Check for slash command pattern without accessing protected attribute
            text_before_str = cast(str, text_before or "")
            if text_before_str.strip().startswith("/") and " " not in text_before_str:
                should_refresh = True

        if should_refresh:
            buf.start_completion(select_first=False)  # type: ignore[reportUnknownMemberType]
    except Exception:
        pass


@kb.add("left")
def _(event):  # type: ignore
    """Support wrapping to previous line when pressing left at column 0."""
    buf = event.current_buffer  # type: ignore
    try:
        doc = buf.document  # type: ignore[reportUnknownMemberType]
        row = cast(int, doc.cursor_position_row)  # type: ignore[reportUnknownMemberType]
        col = cast(int, doc.cursor_position_col)  # type: ignore[reportUnknownMemberType]

        # At the beginning of a non-first line: jump to previous line end.
        if col == 0 and row > 0:
            lines = cast(list[str], doc.lines)  # type: ignore[reportUnknownMemberType]
            prev_row = row - 1
            if 0 <= prev_row < len(lines):
                prev_line = lines[prev_row]
                new_index = doc.translate_row_col_to_index(prev_row, len(prev_line))  # type: ignore[reportUnknownMemberType]
                buf.cursor_position = new_index  # type: ignore[reportUnknownMemberType]
            return

        # Default behavior: move one character left when possible.
        if doc.cursor_position > 0:  # type: ignore[reportUnknownMemberType]
            buf.cursor_left()  # type: ignore[reportUnknownMemberType]
    except Exception:
        pass


@kb.add("right")
def _(event):  # type: ignore
    """Support wrapping to next line when pressing right at line end."""
    buf = event.current_buffer  # type: ignore
    try:
        doc = buf.document  # type: ignore[reportUnknownMemberType]
        row = cast(int, doc.cursor_position_row)  # type: ignore[reportUnknownMemberType]
        col = cast(int, doc.cursor_position_col)  # type: ignore[reportUnknownMemberType]
        lines = cast(list[str], doc.lines)  # type: ignore[reportUnknownMemberType]

        current_line = lines[row] if 0 <= row < len(lines) else ""
        at_line_end = col >= len(current_line)
        is_last_line = row >= len(lines) - 1 if lines else True

        # At end of a non-last line: jump to next line start.
        if at_line_end and not is_last_line:
            next_row = row + 1
            new_index = doc.translate_row_col_to_index(next_row, 0)  # type: ignore[reportUnknownMemberType]
            buf.cursor_position = new_index  # type: ignore[reportUnknownMemberType]
            return

        # Default behavior: move one character right when possible.
        if doc.cursor_position < len(doc.text):  # type: ignore[reportUnknownMemberType]
            buf.cursor_right()  # type: ignore[reportUnknownMemberType]
    except Exception:
        pass


class PromptToolkitInput(InputProviderABC):
    def __init__(self, prompt: str = "❯ ", status_provider: Callable[[], REPLStatusSnapshot] | None = None):  # ▌
        self._status_provider = status_provider

        # Mouse is disabled by default; only enabled when input becomes multi-line.
        self._mouse_enabled: bool = False

        project = str(Path.cwd()).strip("/").replace("/", "-")
        history_path = Path.home() / ".klaude" / "projects" / f"{project}" / "input_history.txt"

        if not history_path.parent.exists():
            history_path.parent.mkdir(parents=True, exist_ok=True)
        if not history_path.exists():
            history_path.touch()

        mouse_support_filter = Condition(lambda: self._mouse_enabled)

        self._session: PromptSession[str] = PromptSession(
            [(INPUT_PROMPT_STYLE, prompt)],
            history=FileHistory(history_path),
            multiline=True,
            prompt_continuation=[(INPUT_PROMPT_STYLE, "  ")],
            key_bindings=kb,
            completer=ThreadedCompleter(_ComboCompleter()),
            complete_while_typing=True,
            erase_when_done=True,
            bottom_toolbar=self._render_bottom_toolbar,
            mouse_support=mouse_support_filter,
            style=Style.from_dict(
                {
                    "completion-menu": "bg:default",
                    "completion-menu.border": "bg:default",
                    "scrollbar.background": "bg:default",
                    "scrollbar.button": "bg:default",
                    "completion-menu.completion": f"bg:default fg:{COMPLETION_MENU}",
                    "completion-menu.meta.completion": f"bg:default fg:{COMPLETION_MENU}",
                    "completion-menu.completion.current": f"noreverse bg:default fg:{COMPLETION_SELECTED} bold",
                    "completion-menu.meta.completion.current": f"bg:default fg:{COMPLETION_SELECTED} bold",
                }
            ),
        )

        try:
            self._session.default_buffer.on_text_changed += self._on_buffer_text_changed
        except Exception:
            # If we can't hook the buffer events for any reason, fall back to static behavior.
            pass

    def _render_bottom_toolbar(self) -> FormattedText:
        """Render bottom toolbar with working directory, git branch on left, model name and context usage on right.

        If an update is available, only show the update message on the left side.
        """
        # Check for update message first
        update_message: str | None = None
        if self._status_provider:
            try:
                status = self._status_provider()
                update_message = status.update_message
            except Exception:
                pass

        # If update available, show only the update message
        if update_message:
            left_text = " " + update_message
            try:
                terminal_width = shutil.get_terminal_size().columns
                padding = " " * max(0, terminal_width - len(left_text))
            except Exception:
                padding = ""
            toolbar_text = left_text + padding
            return FormattedText([("#ansiyellow", toolbar_text)])

        # Normal mode: Left side: path and git branch
        left_parts: list[str] = []
        left_parts.append(show_path_with_tilde())

        git_branch = get_current_git_branch()
        if git_branch:
            left_parts.append(git_branch)

        # Right side: status info
        right_parts: list[str] = []
        if self._status_provider:
            try:
                status = self._status_provider()
                model_name = status.model_name or "N/A"
                right_parts.append(model_name)

                # Add context if available
                if status.context_usage_percent is not None:
                    right_parts.append(f"context {status.context_usage_percent:.1f}%")
            except Exception:
                pass

        # Build left and right text with borders
        left_text = " " + " · ".join(left_parts)
        right_text = (" · ".join(right_parts) + " ") if right_parts else " "

        # Calculate padding
        try:
            terminal_width = shutil.get_terminal_size().columns
            used_width = len(left_text) + len(right_text)
            padding = " " * max(0, terminal_width - used_width)
        except Exception:
            padding = ""

        # Build result with style
        toolbar_text = left_text + padding + right_text
        return FormattedText([("#ansiblue", toolbar_text)])

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    @override
    async def iter_inputs(self) -> AsyncIterator[str]:
        while True:
            # For each new prompt, start with mouse disabled so users can select history.
            self._mouse_enabled = False
            with patch_stdout():
                line: str = await self._session.prompt_async()
            yield line

    def _on_buffer_text_changed(self, buf: Buffer) -> None:
        """Toggle mouse support based on current buffer content.

        Mouse stays disabled when input is empty. It is enabled only when
        the user has entered more than one line of text.
        """
        try:
            text = buf.text
        except Exception:
            return
        self._mouse_enabled = self._should_enable_mouse(text)

    def _should_enable_mouse(self, text: str) -> bool:
        """Return True when mouse support should be enabled for current input."""
        if not text.strip():
            return False
        # Enable mouse only when input spans multiple lines.
        return "\n" in text


class _CmdResult(NamedTuple):
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

    def get_completions(self, document: Document, complete_event) -> Iterable[Completion]:  # type: ignore[override]
        # Only complete on first line
        if document.cursor_position_row != 0:
            return iter([])

        text_before = document.current_line_before_cursor
        m = self._SLASH_TOKEN_RE.search(text_before)
        if not m:
            return iter([])

        frag = m.group("frag")
        token_start = len(text_before) - len(f"/{frag}")
        start_position = token_start - len(text_before)  # negative offset

        # Get available commands
        commands = get_commands()

        # Filter commands that match the fragment
        matched: list[tuple[str, object, str]] = []
        for cmd_name, cmd_obj in sorted(commands.items(), key=lambda x: str(x[1].name)):
            if cmd_name.startswith(frag):
                hint = " [args]" if cmd_obj.support_addition_params else ""
                matched.append((cmd_name, cmd_obj, hint))

        if not matched:
            return iter([])

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
                f"<b>{cmd_name}</b>{hint}{padding}<style color='ansibrightblack'>— {cmd_obj.summary}</style>"  # pyright: ignore[reportUnknownMemberType, reportAttributeAccessIssue]
            )
            completion_text = f"/{cmd_name} "
            yield Completion(text=completion_text, start_position=start_position, display=display_text)

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

    def get_completions(self, document: Document, complete_event) -> Iterable[Completion]:  # type: ignore[override]
        # Try slash command completion first (only on first line)
        if document.cursor_position_row == 0:
            if self._slash_completer.is_slash_command_context(document):
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

    _AT_TOKEN_RE = re.compile(r"(^|\s)@(?P<frag>[^\s]*)$")

    def __init__(self, debounce_sec: float = 0.25, cache_ttl_sec: float = 10.0, max_results: int = 20):
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

        frag = m.group("frag")  # text after '@' and before cursor (no spaces)
        token_start_in_input = len(text_before) - len(f"@{frag}")

        cwd = Path.cwd()

        # If no fragment yet, show lightweight suggestions from current directory
        if frag.strip() == "":
            suggestions = self._suggest_for_empty_fragment(cwd)
            if not suggestions:
                return []  # type: ignore[reportUnknownVariableType]
            start_position = token_start_in_input - len(text_before)
            for s in suggestions[: self._max_results]:
                yield Completion(text=f"@{s} ", start_position=start_position, display=s)
            return []  # type: ignore[reportUnknownVariableType]

        # Gather suggestions with debounce/caching based on search keyword
        suggestions = self._complete_paths(cwd, frag)
        if not suggestions:
            return []  # type: ignore[reportUnknownVariableType]

        # Prepare Completion objects. Replace from the '@' character.
        start_position = token_start_in_input - len(text_before)  # negative
        for s in suggestions[: self._max_results]:
            # Insert '@<path> ' so that subsequent typing does not keep triggering
            yield Completion(text=f"@{s} ", start_position=start_position, display=s)

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
        self, paths_from_root: list[str], cwd: Path, keyword_norm: str, ignored_paths: set[str] | None = None
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
            score = (is_ignored, 0 if base_pos != -1 else 1, base_pos if base_pos != -1 else 10_000, path_pos, len(p))

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
        try:
            p = subprocess.run(
                cmd,
                cwd=str(cwd) if cwd else None,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=1.5,
            )
            if p.returncode == 0:
                lines = [ln.strip() for ln in p.stdout.splitlines() if ln.strip()]
                return _CmdResult(True, lines)
            return _CmdResult(False, [])
        except Exception:
            return _CmdResult(False, [])
