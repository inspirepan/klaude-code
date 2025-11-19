from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from collections.abc import AsyncIterator, Callable, Iterable
from pathlib import Path
from typing import NamedTuple, cast, override

from PIL import Image, ImageGrab
from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion, ThreadedCompleter
from prompt_toolkit.document import Document
from prompt_toolkit.formatted_text import HTML, FormattedText
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.patch_stdout import patch_stdout
from prompt_toolkit.styles import Style

from codex_mini.command import get_commands
from codex_mini.ui.base.input_abc import InputProviderABC
from codex_mini.ui.base.utils import get_current_git_branch, show_path_with_tilde


class REPLStatusSnapshot(NamedTuple):
    """Snapshot of REPL status for bottom toolbar display."""

    model_name: str
    context_usage_percent: float | None
    llm_calls: int
    tool_calls: int


def _set_cursor_style(code: int) -> None:
    """Set cursor style via DECSCUSR (CSI Ps SP q).

    Common values:
      0/1: blinking block, 2: steady block,
      3: blinking underline, 4: steady underline,
      5: blinking bar, 6: steady bar
    """
    try:
        if sys.stdout.isatty():
            os.write(1, f"\x1b[{code} q".encode())
    except Exception:
        pass


kb = KeyBindings()

COMPLETION_SELECTED = "#5869f7"
COMPLETION_MENU = "ansibrightblack"
INPUT_PROMPT_STYLE = "ansicyan"

IMAGES_DIR = Path.home() / ".config" / "codex-mini" / "clipboard" / "images"
IMAGE_MAP_FILE = Path.home() / ".config" / "codex-mini" / "clipboard" / "last_clipboard_images.json"

_pending_images: dict[str, str] = {}
_image_counter: int = 1


@kb.add("c-v")
def _(event):  # type: ignore
    """Paste image from clipboard as [Image #N]."""
    global _image_counter
    try:
        img = ImageGrab.grabclipboard()
        if img and isinstance(img, Image.Image):
            # Ensure directory exists
            if not IMAGES_DIR.exists():
                IMAGES_DIR.mkdir(parents=True, exist_ok=True)

            # Save image
            filename = f"clipboard_{uuid.uuid4().hex[:8]}.png"
            path = IMAGES_DIR / filename
            img.save(path, "PNG")

            # Insert tag and track it
            tag = f"[Image #{_image_counter}]"
            _pending_images[tag] = str(path)
            _image_counter += 1

            event.current_buffer.insert_text(tag)  # pyright: ignore[reportUnknownMemberType]
    except Exception:
        pass


@kb.add("enter")
def _(event):  # type: ignore
    global _image_counter, _pending_images
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

    # If we are submitting, save the image map
    try:
        if not IMAGE_MAP_FILE.parent.exists():
            IMAGE_MAP_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(IMAGE_MAP_FILE, "w") as f:
            json.dump(_pending_images, f)
    except Exception:
        pass

    # Clean up pending images for next turn (though this runs before the yield,
    # we presume the interpreter will pick it up via the file before next prompt)
    _pending_images = {}
    _image_counter = 1

    buf.validate_and_handle()  # type: ignore


@kb.add("c-j")
def _(event):  # type: ignore
    event.current_buffer.insert_text("\n")  # type: ignore


@kb.add("backspace")
def _(event):  # type: ignore
    """Ensure completions refresh on backspace when editing an @token.

    We delete the character before cursor (default behavior), then explicitly
    trigger completion refresh if the caret is still within an @... token.
    """
    buf = event.current_buffer  # type: ignore
    # Perform the default backspace behavior
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


class PromptToolkitInput(InputProviderABC):
    def __init__(self, prompt: str = "▌ ", status_provider: Callable[[], REPLStatusSnapshot] | None = None):
        self._status_provider = status_provider

        project = str(Path.cwd()).strip("/").replace("/", "-")
        history_path = Path.home() / ".config" / "codex-mini" / "project" / f"{project}" / "input_history.txt"

        if not history_path.parent.exists():
            history_path.parent.mkdir(parents=True, exist_ok=True)
        if not history_path.exists():
            history_path.touch()

        self._session: PromptSession[str] = PromptSession(
            [(INPUT_PROMPT_STYLE, prompt)],
            history=FileHistory(history_path),
            multiline=True,
            prompt_continuation=[(INPUT_PROMPT_STYLE, prompt)],
            key_bindings=kb,
            completer=ThreadedCompleter(_ComboCompleter()),
            complete_while_typing=True,
            erase_when_done=True,
            bottom_toolbar=self._render_bottom_toolbar,
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

    def _render_bottom_toolbar(self) -> FormattedText:
        """Render bottom toolbar with working directory, git branch on left, model name and context usage on right."""
        # Left side: path and git branch
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

    async def start(self) -> None:  # noqa: D401
        _set_cursor_style(5)

    async def stop(self) -> None:  # noqa: D401
        _set_cursor_style(0)  # restore terminal default

    @override
    async def iter_inputs(self) -> AsyncIterator[str]:
        while True:
            with patch_stdout():
                line: str = await self._session.prompt_async()
            yield line


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
                f"<b>{cmd_name}</b>{hint}{padding}<style color='ansibrightblack'>— {cmd_obj.summary}</style>"
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
                    return self._filter_and_format(self._last_results, cwd, key_norm)

        # Cache TTL: reuse cached results for same query within TTL
        if self._last_results and self._last_query_key == query_key and now - self._last_results_time < self._cache_ttl:
            return self._filter_and_format(self._last_results, cwd, key_norm)

        # Prefer fd; otherwise fallback to rg --files
        results: list[str] = []
        if self._has_cmd("fd"):
            # Use fd to search anywhere in full path (files and directories), case-insensitive
            results = self._run_fd_search(cwd, key_norm)
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
        else:
            return []

        # Update caches
        self._last_cmd_time = now
        self._last_query_key = query_key
        self._last_results = results
        self._last_results_time = now
        return self._filter_and_format(results, cwd, key_norm)

    def _filter_and_format(self, paths_from_root: list[str], cwd: Path, keyword_norm: str) -> list[str]:
        # Filter to keyword (case-insensitive) and rank by basename hit first, then path hit position, then length
        # Since both fd and rg now search from current directory, all paths are relative to cwd
        kn = keyword_norm
        out: list[tuple[str, tuple[int, int, int]]] = []
        for p in paths_from_root:
            pl = p.lower()
            if kn not in pl:
                continue

            # Use path directly since it's already relative to current directory
            rel_to_cwd = p.lstrip("./")
            base = os.path.basename(p).lower()
            base_pos = base.find(kn)
            path_pos = pl.find(kn)
            score = (0 if base_pos != -1 else 1, base_pos if base_pos != -1 else 10_000, path_pos, len(p))

            # Append trailing slash for directories
            full_path = cwd / rel_to_cwd
            if full_path.is_dir() and not rel_to_cwd.endswith("/"):
                rel_to_cwd = rel_to_cwd + "/"
            out.append((rel_to_cwd, score))  # type: ignore[reportArgumentType]
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
    def _run_fd_search(self, cwd: Path, keyword_norm: str) -> list[str]:
        # Use fd regex matching anywhere in the full path; escape user input
        # Fixed to search only in current working directory
        pattern = self._escape_regex(keyword_norm)
        cmd = [
            "fd",
            "--color=never",
            "--type",
            "f",
            "--type",
            "d",
            "--hidden",
            "--no-ignore",
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
        # Run fd from current working directory
        r = self._run_cmd(cmd, cwd=cwd)
        return r.lines if r.ok else []

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
