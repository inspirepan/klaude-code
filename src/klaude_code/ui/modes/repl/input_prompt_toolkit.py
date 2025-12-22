from __future__ import annotations

import contextlib
import shutil
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import NamedTuple, override

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import ThreadedCompleter
from prompt_toolkit.cursor_shapes import CursorShape
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.history import FileHistory
from prompt_toolkit.patch_stdout import patch_stdout
from prompt_toolkit.styles import Style

from klaude_code.protocol.model import UserInputPayload
from klaude_code.ui.core.input import InputProviderABC
from klaude_code.ui.modes.repl.clipboard import capture_clipboard_tag, copy_to_clipboard, extract_images_from_text
from klaude_code.ui.modes.repl.completers import AT_TOKEN_PATTERN, create_repl_completer
from klaude_code.ui.modes.repl.key_bindings import create_key_bindings
from klaude_code.ui.renderers.user_input import USER_MESSAGE_MARK
from klaude_code.ui.terminal.color import is_light_terminal_background
from klaude_code.ui.utils.common import get_current_git_branch, show_path_with_tilde


class REPLStatusSnapshot(NamedTuple):
    """Snapshot of REPL status for bottom toolbar display."""

    model_name: str
    context_usage_percent: float | None
    llm_calls: int
    tool_calls: int
    update_message: str | None = None


COMPLETION_SELECTED_DARK_BG = "#8b9bff"
COMPLETION_SELECTED_LIGHT_BG = "#5869f7"
COMPLETION_SELECTED_UNKNOWN_BG = "#7080f0"
COMPLETION_MENU = "ansibrightblack"
INPUT_PROMPT_STYLE = "ansimagenta bold"
PLACEHOLDER_TEXT_STYLE_DARK_BG = "fg:#5a5a5a italic"
PLACEHOLDER_TEXT_STYLE_LIGHT_BG = "fg:#7a7a7a italic"
PLACEHOLDER_TEXT_STYLE_UNKNOWN_BG = "fg:#8a8a8a italic"
PLACEHOLDER_SYMBOL_STYLE_DARK_BG = "bg:#2a2a2a fg:#5a5a5a"
PLACEHOLDER_SYMBOL_STYLE_LIGHT_BG = "bg:#e6e6e6 fg:#7a7a7a"
PLACEHOLDER_SYMBOL_STYLE_UNKNOWN_BG = "bg:#2a2a2a fg:#8a8a8a"


class PromptToolkitInput(InputProviderABC):
    def __init__(
        self,
        prompt: str = USER_MESSAGE_MARK,
        status_provider: Callable[[], REPLStatusSnapshot] | None = None,
        pre_prompt: Callable[[], None] | None = None,
        post_prompt: Callable[[], None] | None = None,
    ):  # ▌
        self._status_provider = status_provider
        self._pre_prompt = pre_prompt
        self._post_prompt = post_prompt
        self._is_light_terminal_background = is_light_terminal_background(timeout=0.2)

        project = str(Path.cwd()).strip("/").replace("/", "-")
        history_path = Path.home() / ".klaude" / "projects" / project / "input" / "input_history.txt"

        history_path.parent.mkdir(parents=True, exist_ok=True)
        history_path.touch(exist_ok=True)

        # Create key bindings with injected dependencies
        kb = create_key_bindings(
            capture_clipboard_tag=capture_clipboard_tag,
            copy_to_clipboard=copy_to_clipboard,
            at_token_pattern=AT_TOKEN_PATTERN,
        )

        # Select completion selected color based on terminal background
        if self._is_light_terminal_background is True:
            completion_selected = COMPLETION_SELECTED_LIGHT_BG
        elif self._is_light_terminal_background is False:
            completion_selected = COMPLETION_SELECTED_DARK_BG
        else:
            completion_selected = COMPLETION_SELECTED_UNKNOWN_BG

        self._session: PromptSession[str] = PromptSession(
            [(INPUT_PROMPT_STYLE, prompt)],
            history=FileHistory(str(history_path)),
            multiline=True,
            cursor=CursorShape.BLINKING_BEAM,
            prompt_continuation=[(INPUT_PROMPT_STYLE, "  ")],
            key_bindings=kb,
            completer=ThreadedCompleter(create_repl_completer()),
            complete_while_typing=True,
            erase_when_done=True,
            bottom_toolbar=self._render_bottom_toolbar,
            mouse_support=False,
            style=Style.from_dict(
                {
                    "completion-menu": "bg:default",
                    "completion-menu.border": "bg:default",
                    "scrollbar.background": "bg:default",
                    "scrollbar.button": "bg:default",
                    "completion-menu.completion": f"bg:default fg:{COMPLETION_MENU}",
                    "completion-menu.meta.completion": f"bg:default fg:{COMPLETION_MENU}",
                    "completion-menu.completion.current": f"noreverse bg:default fg:{completion_selected} bold",
                    "completion-menu.meta.completion.current": f"bg:default fg:{completion_selected} bold",
                }
            ),
        )

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
        return FormattedText([("#2c7eac", toolbar_text)])

    def _render_input_placeholder(self) -> FormattedText:
        if self._is_light_terminal_background is True:
            text_style = PLACEHOLDER_TEXT_STYLE_LIGHT_BG
            symbol_style = PLACEHOLDER_SYMBOL_STYLE_LIGHT_BG
        elif self._is_light_terminal_background is False:
            text_style = PLACEHOLDER_TEXT_STYLE_DARK_BG
            symbol_style = PLACEHOLDER_SYMBOL_STYLE_DARK_BG
        else:
            text_style = PLACEHOLDER_TEXT_STYLE_UNKNOWN_BG
            symbol_style = PLACEHOLDER_SYMBOL_STYLE_UNKNOWN_BG

        return FormattedText(
            [
                (text_style, " " * 10),
                (symbol_style, " @ "),
                (text_style, " "),
                (text_style, "files"),
                (text_style, "  "),
                (symbol_style, " $ "),
                (text_style, " "),
                (text_style, "skills"),
                (text_style, "  "),
                (symbol_style, " / "),
                (text_style, " "),
                (text_style, "commands"),
            ]
        )

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    @override
    async def iter_inputs(self) -> AsyncIterator[UserInputPayload]:
        while True:
            if self._pre_prompt is not None:
                with contextlib.suppress(Exception):
                    self._pre_prompt()
            with patch_stdout():
                line: str = await self._session.prompt_async(placeholder=self._render_input_placeholder())
            if self._post_prompt is not None:
                with contextlib.suppress(Exception):
                    self._post_prompt()

            # Extract images referenced in the input text
            images = extract_images_from_text(line)

            yield UserInputPayload(text=line, images=images if images else None)

    # Note: Mouse support is intentionally disabled at the PromptSession
    # level so that terminals retain their native scrollback behavior.
