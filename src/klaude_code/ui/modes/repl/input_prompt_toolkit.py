from __future__ import annotations

import shutil
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import NamedTuple, override

from prompt_toolkit import PromptSession
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.completion import ThreadedCompleter
from prompt_toolkit.filters import Condition
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.history import FileHistory
from prompt_toolkit.patch_stdout import patch_stdout
from prompt_toolkit.styles import Style

from klaude_code.protocol.model import UserInputPayload
from klaude_code.ui.core.input import InputProviderABC
from klaude_code.ui.modes.repl.clipboard import capture_clipboard_tag, copy_to_clipboard, extract_images_from_text
from klaude_code.ui.modes.repl.completers import AT_TOKEN_PATTERN, create_repl_completer
from klaude_code.ui.modes.repl.key_bindings import create_key_bindings
from klaude_code.ui.utils.common import get_current_git_branch, show_path_with_tilde


class REPLStatusSnapshot(NamedTuple):
    """Snapshot of REPL status for bottom toolbar display."""

    model_name: str
    context_usage_percent: float | None
    llm_calls: int
    tool_calls: int
    update_message: str | None = None


COMPLETION_SELECTED = "#5869f7"
COMPLETION_MENU = "ansibrightblack"
INPUT_PROMPT_STYLE = "ansimagenta"


class PromptToolkitInput(InputProviderABC):
    def __init__(
        self,
        prompt: str = "❯ ",
        status_provider: Callable[[], REPLStatusSnapshot] | None = None,
    ):  # ▌
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

        # Create key bindings with injected dependencies
        kb = create_key_bindings(
            capture_clipboard_tag=capture_clipboard_tag,
            copy_to_clipboard=copy_to_clipboard,
            at_token_pattern=AT_TOKEN_PATTERN,
        )

        self._session: PromptSession[str] = PromptSession(
            [(INPUT_PROMPT_STYLE, prompt)],
            history=FileHistory(history_path),
            multiline=True,
            prompt_continuation=[(INPUT_PROMPT_STYLE, "  ")],
            key_bindings=kb,
            completer=ThreadedCompleter(create_repl_completer()),
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
    async def iter_inputs(self) -> AsyncIterator[UserInputPayload]:
        while True:
            # For each new prompt, start with mouse disabled so users can select history.
            self._mouse_enabled = False
            with patch_stdout():
                line: str = await self._session.prompt_async()

            # Extract images referenced in the input text
            images = extract_images_from_text(line)

            yield UserInputPayload(text=line, images=images if images else None)

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
