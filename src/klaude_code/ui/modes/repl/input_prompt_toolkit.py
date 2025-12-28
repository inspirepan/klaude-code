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
from prompt_toolkit.layout.containers import Container, FloatContainer
from prompt_toolkit.layout.menus import CompletionsMenu, MultiColumnCompletionsMenu
from prompt_toolkit.patch_stdout import patch_stdout
from prompt_toolkit.styles import Style

from klaude_code.protocol.model import UserInputPayload
from klaude_code.ui.core.input import InputProviderABC
from klaude_code.ui.modes.repl.clipboard import capture_clipboard_tag, copy_to_clipboard, extract_images_from_text
from klaude_code.ui.modes.repl.completers import AT_TOKEN_PATTERN, create_repl_completer
from klaude_code.ui.modes.repl.key_bindings import create_key_bindings
from klaude_code.ui.renderers.user_input import USER_MESSAGE_MARK
from klaude_code.ui.terminal.color import is_light_terminal_background


class REPLStatusSnapshot(NamedTuple):
    """Snapshot of REPL status for bottom toolbar display."""

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


def _left_align_completion_menus(container: Container) -> None:
    """Force completion menus to render at column 0.

    prompt_toolkit's default completion menu floats are positioned relative to the
    cursor (`xcursor=True`). That makes the popup indent as the caret moves.
    We walk the layout tree and rewrite the Float positioning for completion menus
    to keep them fixed at the left edge.
    """

    if isinstance(container, FloatContainer):
        for flt in container.floats:
            if isinstance(flt.content, (CompletionsMenu, MultiColumnCompletionsMenu)):
                flt.xcursor = False
                flt.left = 0

    for child in container.get_children():
        _left_align_completion_menus(child)


class PromptToolkitInput(InputProviderABC):
    def __init__(
        self,
        prompt: str = USER_MESSAGE_MARK,
        status_provider: Callable[[], REPLStatusSnapshot] | None = None,
        pre_prompt: Callable[[], None] | None = None,
        post_prompt: Callable[[], None] | None = None,
        is_light_background: bool | None = None,
    ):  # ▌
        self._status_provider = status_provider
        self._pre_prompt = pre_prompt
        self._post_prompt = post_prompt
        # Use provided value if available to avoid redundant TTY queries that may interfere
        # with prompt_toolkit's terminal state after interactive UIs have been used.
        self._is_light_terminal_background = (
            is_light_background if is_light_background is not None else is_light_terminal_background(timeout=0.2)
        )

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

        # Keep completion popups left-aligned instead of shifting with the caret.
        with contextlib.suppress(Exception):
            _left_align_completion_menus(self._session.app.layout.container)

        def _select_first_completion_on_open(buf) -> None:  # type: ignore[no-untyped-def]
            """Default to selecting the first completion without inserting it."""

            try:
                state = buf.complete_state  # type: ignore[reportUnknownMemberType]
                if state is None:
                    return
                if not state.completions:  # type: ignore[reportUnknownMemberType]
                    return
                if state.complete_index is None:  # type: ignore[reportUnknownMemberType]
                    state.complete_index = 0  # type: ignore[reportUnknownMemberType]
                    with contextlib.suppress(Exception):
                        self._session.app.invalidate()
            except Exception:
                return

        # Ensure the completion menu always has a default selection (first item),
        # so Enter/Tab can accept immediately.
        self._session.default_buffer.on_completions_changed += _select_first_completion_on_open

    def _get_bottom_toolbar(self) -> FormattedText | None:
        """Return bottom toolbar content only when there's an update message available."""
        if not self._status_provider:
            return None

        try:
            status = self._status_provider()
            update_message = status.update_message
        except (AttributeError, RuntimeError):
            return None

        if not update_message:
            return None

        left_text = " " + update_message
        try:
            terminal_width = shutil.get_terminal_size().columns
            padding = " " * max(0, terminal_width - len(left_text))
        except (OSError, ValueError):
            padding = ""

        toolbar_text = left_text + padding
        return FormattedText([("#ansiyellow", toolbar_text)])

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

            # Only show bottom toolbar if there's an update message
            bottom_toolbar = self._get_bottom_toolbar()

            with patch_stdout():
                line: str = await self._session.prompt_async(
                    placeholder=self._render_input_placeholder(),
                    bottom_toolbar=bottom_toolbar,
                )
            if self._post_prompt is not None:
                with contextlib.suppress(Exception):
                    self._post_prompt()

            # Extract images referenced in the input text
            images = extract_images_from_text(line)

            yield UserInputPayload(text=line, images=images if images else None)

    # Note: Mouse support is intentionally disabled at the PromptSession
    # level so that terminals retain their native scrollback behavior.
