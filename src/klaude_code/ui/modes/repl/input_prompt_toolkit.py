from __future__ import annotations

import asyncio
import contextlib
import shutil
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from typing import NamedTuple, override

import prompt_toolkit.layout.menus as pt_menus
from prompt_toolkit import PromptSession
from prompt_toolkit.application.current import get_app
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.completion import Completion, ThreadedCompleter
from prompt_toolkit.cursor_shapes import CursorShape
from prompt_toolkit.data_structures import Point
from prompt_toolkit.filters import Condition
from prompt_toolkit.formatted_text import FormattedText, StyleAndTextTuples, to_formatted_text
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import merge_key_bindings
from prompt_toolkit.layout import Float
from prompt_toolkit.layout.containers import Container, FloatContainer, Window
from prompt_toolkit.layout.controls import BufferControl, UIContent
from prompt_toolkit.layout.menus import CompletionsMenu, MultiColumnCompletionsMenu
from prompt_toolkit.patch_stdout import patch_stdout
from prompt_toolkit.styles import Style
from prompt_toolkit.utils import get_cwidth

from klaude_code.config import load_config
from klaude_code.config.config import ModelEntry
from klaude_code.config.thinking import (
    format_current_thinking,
    get_thinking_picker_data,
    parse_thinking_value,
)
from klaude_code.protocol import llm_param
from klaude_code.protocol.commands import CommandInfo
from klaude_code.protocol.model import UserInputPayload
from klaude_code.ui.core.input import InputProviderABC
from klaude_code.ui.modes.repl.clipboard import capture_clipboard_tag, copy_to_clipboard, extract_images_from_text
from klaude_code.ui.modes.repl.completers import AT_TOKEN_PATTERN, create_repl_completer
from klaude_code.ui.modes.repl.key_bindings import create_key_bindings
from klaude_code.ui.renderers.user_input import USER_MESSAGE_MARK
from klaude_code.ui.terminal.color import is_light_terminal_background
from klaude_code.ui.terminal.selector import SelectItem, SelectOverlay, build_model_select_items


class REPLStatusSnapshot(NamedTuple):
    """Snapshot of REPL status for bottom toolbar display."""

    update_message: str | None = None


COMPLETION_SELECTED_DARK_BG = "ansigreen"
COMPLETION_SELECTED_LIGHT_BG = "ansigreen"
COMPLETION_SELECTED_UNKNOWN_BG = "ansigreen"
COMPLETION_MENU = "ansibrightblack"
INPUT_PROMPT_STYLE = "ansimagenta bold"
PLACEHOLDER_TEXT_STYLE_DARK_BG = "fg:#5a5a5a italic"
PLACEHOLDER_TEXT_STYLE_LIGHT_BG = "fg:#7a7a7a italic"
PLACEHOLDER_TEXT_STYLE_UNKNOWN_BG = "fg:#8a8a8a italic"
PLACEHOLDER_SYMBOL_STYLE_DARK_BG = "bg:#2a2a2a fg:#5a5a5a"
PLACEHOLDER_SYMBOL_STYLE_LIGHT_BG = "bg:#e6e6e6 fg:#7a7a7a"
PLACEHOLDER_SYMBOL_STYLE_UNKNOWN_BG = "bg:#2a2a2a fg:#8a8a8a"


# ---------------------------------------------------------------------------
# Layout helpers
# ---------------------------------------------------------------------------


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


def _find_first_float_container(container: Container) -> FloatContainer | None:
    if isinstance(container, FloatContainer):
        return container
    for child in container.get_children():
        found = _find_first_float_container(child)
        if found is not None:
            return found
    return None


def _find_window_for_buffer(container: Container, target_buffer: Buffer) -> Window | None:
    if isinstance(container, Window):
        content = container.content
        if isinstance(content, BufferControl) and content.buffer is target_buffer:
            return container

    for child in container.get_children():
        found = _find_window_for_buffer(child, target_buffer)
        if found is not None:
            return found
    return None


def _patch_completion_menu_controls(container: Container) -> None:
    """Replace prompt_toolkit completion menu controls with customized versions."""
    if isinstance(container, Window):
        content = container.content
        if isinstance(content, pt_menus.CompletionsMenuControl) and not isinstance(
            content, _KlaudeCompletionsMenuControl
        ):
            container.content = _KlaudeCompletionsMenuControl()

    for child in container.get_children():
        _patch_completion_menu_controls(child)


# ---------------------------------------------------------------------------
# Custom completion menu control
# ---------------------------------------------------------------------------


class _KlaudeCompletionsMenuControl(pt_menus.CompletionsMenuControl):
    """CompletionsMenuControl with stable 2-char left prefix.

    Requirements:
    - Add a 2-character prefix for every row.
    - Render "-> " for the selected row, and "  " for non-selected rows.

    Keep completion text unstyled so that the menu's current-row style can
    override it entirely.
    """

    _PREFIX_WIDTH = 2

    def _get_menu_width(self, max_width: int, complete_state: pt_menus.CompletionState) -> int:  # pyright: ignore[reportPrivateImportUsage]
        """Return the width of the main column.

        This is prompt_toolkit's default implementation, except we reserve one
        extra character for the 2-char prefix ("-> "/"  ").
        """
        return min(
            max_width,
            max(
                self.MIN_WIDTH,
                max(get_cwidth(c.display_text) for c in complete_state.completions) + 3,
            ),
        )

    def create_content(self, width: int, height: int) -> UIContent:
        complete_state = get_app().current_buffer.complete_state
        if complete_state:
            completions = complete_state.completions
            index = complete_state.complete_index

            menu_width = self._get_menu_width(width, complete_state)
            menu_meta_width = self._get_menu_meta_width(width - menu_width, complete_state)
            show_meta = self._show_meta(complete_state)

            def get_line(i: int) -> StyleAndTextTuples:
                completion = completions[i]
                is_current_completion = i == index

                result = self._get_menu_item_fragments_with_cursor(
                    completion,
                    is_current_completion,
                    menu_width,
                    space_after=True,
                )
                if show_meta:
                    result += self._get_menu_item_meta_fragments(
                        completion,
                        is_current_completion,
                        menu_meta_width,
                    )
                return result

            return UIContent(
                get_line=get_line,
                cursor_position=Point(x=0, y=index or 0),
                line_count=len(completions),
            )

        return UIContent()

    def _get_menu_item_fragments_with_cursor(
        self,
        completion: Completion,
        is_current_completion: bool,
        width: int,
        *,
        space_after: bool = False,
    ) -> StyleAndTextTuples:
        if is_current_completion:
            style_str = f"class:completion-menu.completion.current {completion.style} {completion.selected_style}"
            prefix = "→ "
        else:
            style_str = "class:completion-menu.completion " + completion.style
            prefix = "  "

        max_text_width = width - self._PREFIX_WIDTH - (1 if space_after else 0)
        text, text_width = pt_menus._trim_formatted_text(completion.display, max_text_width)  # pyright: ignore[reportPrivateUsage]
        padding = " " * (width - self._PREFIX_WIDTH - text_width)

        return to_formatted_text(
            [("", prefix), *text, ("", padding)],
            style=style_str,
        )


# ---------------------------------------------------------------------------
# PromptToolkitInput
# ---------------------------------------------------------------------------


class PromptToolkitInput(InputProviderABC):
    def __init__(
        self,
        prompt: str = USER_MESSAGE_MARK,
        status_provider: Callable[[], REPLStatusSnapshot] | None = None,
        pre_prompt: Callable[[], None] | None = None,
        post_prompt: Callable[[], None] | None = None,
        is_light_background: bool | None = None,
        on_change_model: Callable[[str], Awaitable[None]] | None = None,
        get_current_model_config_name: Callable[[], str | None] | None = None,
        on_change_thinking: Callable[[llm_param.Thinking], Awaitable[None]] | None = None,
        get_current_llm_config: Callable[[], llm_param.LLMConfigParameter | None] | None = None,
        command_info_provider: Callable[[], list[CommandInfo]] | None = None,
    ):
        self._status_provider = status_provider
        self._pre_prompt = pre_prompt
        self._post_prompt = post_prompt
        self._on_change_model = on_change_model
        self._get_current_model_config_name = get_current_model_config_name
        self._on_change_thinking = on_change_thinking
        self._get_current_llm_config = get_current_llm_config
        self._command_info_provider = command_info_provider

        self._toast_message: str | None = None
        self._toast_until: float = 0.0

        # Use provided value if available to avoid redundant TTY queries that may interfere
        # with prompt_toolkit's terminal state after interactive UIs have been used.
        self._is_light_terminal_background = (
            is_light_background if is_light_background is not None else is_light_terminal_background(timeout=0.2)
        )

        self._session = self._build_prompt_session(prompt)
        self._setup_model_picker()
        self._setup_thinking_picker()
        self._apply_layout_customizations()

    def _build_prompt_session(self, prompt: str) -> PromptSession[str]:
        """Build the prompt_toolkit PromptSession with key bindings and styles."""
        project = str(Path.cwd()).strip("/").replace("/", "-")
        history_path = Path.home() / ".klaude" / "projects" / project / "input" / "input_history.txt"
        history_path.parent.mkdir(parents=True, exist_ok=True)
        history_path.touch(exist_ok=True)

        # Model and thinking pickers will be set up later; create placeholder condition
        self._model_picker: SelectOverlay[str] | None = None
        self._thinking_picker: SelectOverlay[str] | None = None
        input_enabled = Condition(
            lambda: (self._model_picker is None or not self._model_picker.is_open)
            and (self._thinking_picker is None or not self._thinking_picker.is_open)
        )

        kb = create_key_bindings(
            capture_clipboard_tag=capture_clipboard_tag,
            copy_to_clipboard=copy_to_clipboard,
            at_token_pattern=AT_TOKEN_PATTERN,
            input_enabled=input_enabled,
            open_model_picker=self._open_model_picker,
            open_thinking_picker=self._open_thinking_picker,
        )

        # Select completion selected color based on terminal background
        if self._is_light_terminal_background is True:
            completion_selected = COMPLETION_SELECTED_LIGHT_BG
        elif self._is_light_terminal_background is False:
            completion_selected = COMPLETION_SELECTED_DARK_BG
        else:
            completion_selected = COMPLETION_SELECTED_UNKNOWN_BG

        return PromptSession(
            [(INPUT_PROMPT_STYLE, prompt)],
            history=FileHistory(str(history_path)),
            multiline=True,
            cursor=CursorShape.BLINKING_BEAM,
            prompt_continuation=[(INPUT_PROMPT_STYLE, "  ")],
            key_bindings=kb,
            completer=ThreadedCompleter(create_repl_completer(command_info_provider=self._command_info_provider)),
            complete_while_typing=True,
            erase_when_done=True,
            mouse_support=False,
            style=Style.from_dict(
                {
                    "completion-menu": "bg:default",
                    "completion-menu.border": "bg:default",
                    "scrollbar.background": "bg:default",
                    "scrollbar.button": "bg:default",
                    "completion-menu.completion": "bg:default fg:default",
                    "completion-menu.meta.completion": f"bg:default fg:{COMPLETION_MENU}",
                    "completion-menu.completion.current": f"noreverse bg:default fg:{completion_selected}",
                    "completion-menu.meta.completion.current": f"bg:default fg:{completion_selected}",
                    # Embedded selector overlay styles
                    "pointer": "ansigreen",
                    "highlighted": "ansigreen",
                    "text": "ansibrightblack",
                    "question": "bold",
                    "msg": "",
                    "meta": "fg:ansibrightblack",
                    "frame.border": "fg:ansibrightblack",
                    "search_prefix": "fg:ansibrightblack",
                    "search_placeholder": "fg:ansibrightblack italic",
                    "search_input": "",
                    # Empty bottom-toolbar style
                    "bottom-toolbar": "bg:default fg:default noreverse",
                    "bottom-toolbar.text": "bg:default fg:default noreverse",
                }
            ),
        )

    def _setup_model_picker(self) -> None:
        """Initialize the model picker overlay and attach it to the layout."""
        model_picker = SelectOverlay[str](
            pointer="→",
            use_search_filter=True,
            search_placeholder="type to search",
            list_height=10,
            on_select=self._handle_model_selected,
        )
        self._model_picker = model_picker

        # Merge overlay key bindings with existing session key bindings
        existing_kb = self._session.key_bindings
        if existing_kb is not None:
            merged_kb = merge_key_bindings([existing_kb, model_picker.key_bindings])
            self._session.key_bindings = merged_kb

        # Attach overlay as a float above the prompt
        with contextlib.suppress(Exception):
            root = self._session.app.layout.container
            overlay_float = Float(content=model_picker.container, bottom=1, left=0)

            # Always attach this overlay at the top level so it is not clipped by
            # small nested FloatContainers (e.g. the completion-menu container).
            if isinstance(root, FloatContainer):
                root.floats.append(overlay_float)
            else:
                self._session.app.layout.container = FloatContainer(content=root, floats=[overlay_float])

    def _setup_thinking_picker(self) -> None:
        """Initialize the thinking picker overlay and attach it to the layout."""
        thinking_picker = SelectOverlay[str](
            pointer="→",
            use_search_filter=False,
            list_height=6,
            on_select=self._handle_thinking_selected,
        )
        self._thinking_picker = thinking_picker

        # Merge overlay key bindings with existing session key bindings
        existing_kb = self._session.key_bindings
        if existing_kb is not None:
            merged_kb = merge_key_bindings([existing_kb, thinking_picker.key_bindings])
            self._session.key_bindings = merged_kb

        # Attach overlay as a float above the prompt
        with contextlib.suppress(Exception):
            root = self._session.app.layout.container
            overlay_float = Float(content=thinking_picker.container, bottom=1, left=0)

            if isinstance(root, FloatContainer):
                root.floats.append(overlay_float)
            else:
                self._session.app.layout.container = FloatContainer(content=root, floats=[overlay_float])

    def _apply_layout_customizations(self) -> None:
        """Apply layout customizations after session is created."""
        # Make the Escape key feel responsive
        with contextlib.suppress(Exception):
            self._session.app.ttimeoutlen = 0.05

        # Keep completion popups left-aligned
        with contextlib.suppress(Exception):
            _left_align_completion_menus(self._session.app.layout.container)

        # Customize completion rendering
        with contextlib.suppress(Exception):
            _patch_completion_menu_controls(self._session.app.layout.container)

        # Reserve more vertical space while the model picker overlay is open.
        # prompt_toolkit's default multiline prompt caps out at ~9 lines.
        self._patch_prompt_height_for_model_picker()

        # Ensure completion menu has default selection
        self._session.default_buffer.on_completions_changed += self._select_first_completion_on_open  # pyright: ignore[reportUnknownMemberType]

    def _patch_prompt_height_for_model_picker(self) -> None:
        if self._model_picker is None and self._thinking_picker is None:
            return

        with contextlib.suppress(Exception):
            root = self._session.app.layout.container
            input_window = _find_window_for_buffer(root, self._session.default_buffer)
            if input_window is None:
                return

            original_height = input_window.height

            def _height():  # type: ignore[no-untyped-def]
                picker_open = (self._model_picker is not None and self._model_picker.is_open) or (
                    self._thinking_picker is not None and self._thinking_picker.is_open
                )
                if picker_open:
                    # Target 20 rows, but cap to the current terminal size.
                    # Leave a small buffer to avoid triggering "Window too small".
                    try:
                        rows = get_app().output.get_size().rows
                    except Exception:
                        rows = 0
                    return max(3, min(20, rows - 2))

                if callable(original_height):
                    return original_height()
                return original_height

            input_window.height = _height

    def _select_first_completion_on_open(self, buf) -> None:  # type: ignore[no-untyped-def]
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

    # -------------------------------------------------------------------------
    # Model picker
    # -------------------------------------------------------------------------

    def _build_model_picker_items(self) -> tuple[list[SelectItem[str]], str | None]:
        config = load_config()
        models: list[ModelEntry] = sorted(
            config.iter_model_entries(only_available=True),
            key=lambda m: m.model_name.lower(),
        )
        if not models:
            return [], None

        items = build_model_select_items(models)

        initial = None
        if self._get_current_model_config_name is not None:
            with contextlib.suppress(Exception):
                initial = self._get_current_model_config_name()
        if initial is None:
            initial = config.main_model
        return items, initial

    def _open_model_picker(self) -> None:
        if self._model_picker is None:
            return
        items, initial = self._build_model_picker_items()
        if not items:
            return
        self._model_picker.set_content(message="Select a model:", items=items, initial_value=initial)
        self._model_picker.open()

    async def _handle_model_selected(self, model_name: str) -> None:
        current = None
        if self._get_current_model_config_name is not None:
            with contextlib.suppress(Exception):
                current = self._get_current_model_config_name()
        if current is not None and model_name == current:
            return
        if self._on_change_model is None:
            return
        await self._on_change_model(model_name)
        self._set_toast(f"model: {model_name}")

    # -------------------------------------------------------------------------
    # Thinking picker
    # -------------------------------------------------------------------------

    def _build_thinking_picker_items(
        self, config: llm_param.LLMConfigParameter
    ) -> tuple[list[SelectItem[str]], str | None]:
        data = get_thinking_picker_data(config)
        if data is None:
            return [], None

        items: list[SelectItem[str]] = [
            SelectItem(title=[("class:text", opt.label + "\n")], value=opt.value, search_text=opt.label)
            for opt in data.options
        ]
        return items, data.current_value

    def _open_thinking_picker(self) -> None:
        if self._thinking_picker is None:
            return
        if self._get_current_llm_config is None:
            return
        config = self._get_current_llm_config()
        if config is None:
            return
        items, initial = self._build_thinking_picker_items(config)
        if not items:
            return
        current = format_current_thinking(config)
        self._thinking_picker.set_content(
            message=f"Select thinking level (current: {current}):", items=items, initial_value=initial
        )
        self._thinking_picker.open()

    async def _handle_thinking_selected(self, value: str) -> None:
        if self._on_change_thinking is None:
            return

        new_thinking = parse_thinking_value(value)
        if new_thinking is None:
            return

        # Build toast label
        if value.startswith("effort:"):
            toast_label = value[7:]
        elif value.startswith("budget:"):
            budget = int(value[7:])
            toast_label = "off" if budget == 0 else f"{budget} tokens"
        else:
            toast_label = "updated"

        await self._on_change_thinking(new_thinking)
        self._set_toast(f"thinking: {toast_label}")

    # -------------------------------------------------------------------------
    # Toast notifications
    # -------------------------------------------------------------------------

    def _set_toast(self, message: str, *, duration_sec: float = 2.0) -> None:
        self._toast_message = message
        self._toast_until = time.monotonic() + duration_sec
        with contextlib.suppress(Exception):
            self._session.app.invalidate()

        async def _clear_later() -> None:
            await asyncio.sleep(duration_sec)
            self._toast_message = None
            self._toast_until = 0.0
            with contextlib.suppress(Exception):
                self._session.app.invalidate()

        with contextlib.suppress(Exception):
            self._session.app.create_background_task(_clear_later())

    # -------------------------------------------------------------------------
    # Bottom toolbar
    # -------------------------------------------------------------------------

    def _get_bottom_toolbar(self) -> FormattedText | None:
        """Return bottom toolbar content.

        This is used inside the prompt_toolkit Application, so avoid printing or
        doing any blocking IO here.
        """
        update_message: str | None = None
        if self._status_provider is not None:
            try:
                status = self._status_provider()
                update_message = status.update_message
            except (AttributeError, RuntimeError):
                update_message = None

        toast: str | None = None
        now = time.monotonic()
        if self._toast_message is not None and now < self._toast_until:
            toast = self._toast_message

        # If nothing to show, return a blank line to actively clear any previously
        # rendered content. (When `bottom_toolbar` is a callable, prompt_toolkit
        # will still reserve the toolbar line.)
        if not toast and not update_message:
            try:
                terminal_width = shutil.get_terminal_size().columns
            except (OSError, ValueError):
                terminal_width = 0
            return FormattedText([("", " " * max(0, terminal_width))])

        parts = [p for p in [toast, update_message] if p]
        left_text = " " + " · ".join(parts)
        try:
            terminal_width = shutil.get_terminal_size().columns
            padding = " " * max(0, terminal_width - len(left_text))
        except (OSError, ValueError):
            padding = ""

        toolbar_text = left_text + padding
        return FormattedText([("#ansiyellow", toolbar_text)])

    # -------------------------------------------------------------------------
    # Placeholder
    # -------------------------------------------------------------------------

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
                (text_style, "  "),
                (symbol_style, " ctrl-l "),
                (text_style, " "),
                (text_style, "models"),
            ]
        )

    # -------------------------------------------------------------------------
    # InputProviderABC implementation
    # -------------------------------------------------------------------------

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
                line: str = await self._session.prompt_async(
                    placeholder=self._render_input_placeholder(),
                    bottom_toolbar=self._get_bottom_toolbar,
                )
            if self._post_prompt is not None:
                with contextlib.suppress(Exception):
                    self._post_prompt()

            # Extract images referenced in the input text
            images = extract_images_from_text(line)

            yield UserInputPayload(text=line, images=images if images else None)

    # Note: Mouse support is intentionally disabled at the PromptSession
    # level so that terminals retain their native scrollback behavior.
