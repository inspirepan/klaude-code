from __future__ import annotations

import contextlib
import shutil
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
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.layout.menus import CompletionsMenu, MultiColumnCompletionsMenu
from prompt_toolkit.patch_stdout import patch_stdout
from prompt_toolkit.styles import Style
from prompt_toolkit.utils import get_cwidth

from klaude_code.config import load_config
from klaude_code.config.model_matcher import match_model_from_config
from klaude_code.config.thinking import (
    format_current_thinking,
    get_thinking_picker_data,
    parse_thinking_value,
)
from klaude_code.protocol import llm_param
from klaude_code.protocol.commands import CommandInfo
from klaude_code.protocol.message import UserInputPayload
from klaude_code.tui.components.user_input import USER_MESSAGE_MARK
from klaude_code.tui.input.completers import AT_TOKEN_PATTERN, create_repl_completer
from klaude_code.tui.input.drag_drop import convert_dropped_text
from klaude_code.tui.input.images import (
    capture_clipboard_tag,
    extract_images_from_text,
)
from klaude_code.tui.input.key_bindings import create_key_bindings
from klaude_code.tui.input.paste import expand_paste_markers
from klaude_code.tui.terminal.color import is_light_terminal_background
from klaude_code.tui.terminal.selector import SelectItem, SelectOverlay, build_model_select_items
from klaude_code.ui.core.input import InputProviderABC


class REPLStatusSnapshot(NamedTuple):
    """Snapshot of REPL status for bottom toolbar display."""

    update_message: str | None = None
    debug_log_path: str | None = None


COMPLETION_SELECTED_DARK_BG = "ansigreen"
COMPLETION_SELECTED_LIGHT_BG = "ansigreen"
COMPLETION_SELECTED_UNKNOWN_BG = "ansigreen"
COMPLETION_MENU = "ansibrightblack"
INPUT_PROMPT_STYLE = "ansimagenta bold"
INPUT_PROMPT_BASH_STYLE = "ansigreen bold"
PLACEHOLDER_TEXT_STYLE_DARK_BG = "fg:#5a5a5a"
PLACEHOLDER_TEXT_STYLE_LIGHT_BG = "fg:#7a7a7a"
PLACEHOLDER_TEXT_STYLE_UNKNOWN_BG = "fg:#8a8a8a"
PLACEHOLDER_SYMBOL_STYLE_DARK_BG = "fg:ansiblue"
PLACEHOLDER_SYMBOL_STYLE_LIGHT_BG = "fg:ansiblue"
PLACEHOLDER_SYMBOL_STYLE_UNKNOWN_BG = "fg:ansiblue"


# ---------------------------------------------------------------------------
# Layout helpers
# ---------------------------------------------------------------------------


def _left_align_completion_menus(container: Container) -> None:
    """Force completion menus to render at column 0.

    prompt_toolkit's default completion menu floats are positioned relative to the
    cursor (`xcursor=True`). That makes the popup indent as the caret moves.
    We walk the layout tree and rewrite the Float positioning for completion menus
    to keep them fixed at the left edge.

    Note: We intentionally keep Y positioning (ycursor) unchanged so that the
    completion menu stays near the cursor/input line.
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
        self._prompt_text = prompt
        self._status_provider = status_provider
        self._pre_prompt = pre_prompt
        self._post_prompt = post_prompt
        self._on_change_model = on_change_model
        self._get_current_model_config_name = get_current_model_config_name
        self._on_change_thinking = on_change_thinking
        self._get_current_llm_config = get_current_llm_config
        self._command_info_provider = command_info_provider

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
            # Use a stable prompt string; we override the style dynamically in prompt_async.
            [(INPUT_PROMPT_STYLE, prompt)],
            history=FileHistory(str(history_path)),
            multiline=True,
            cursor=CursorShape.BLINKING_BEAM,
            key_bindings=kb,
            completer=ThreadedCompleter(create_repl_completer(command_info_provider=self._command_info_provider)),
            complete_while_typing=True,
            # Keep the bottom toolbar stable while completion menus open/close.
            # Reserving space dynamically can make the non-fullscreen prompt
            # "jump" by printing extra lines.
            reserve_space_for_menu=0,
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
                    "frame.border": "fg:ansibrightblack dim",
                    "search_prefix": "ansibrightblack",
                    "search_placeholder": "fg:ansibrightblack italic",
                    "search_input": "",
                    "search_success": "noinherit fg:ansigreen",
                    "search_none": "noinherit fg:ansired",
                    # Empty bottom-toolbar style
                    "bottom-toolbar": "bg:default fg:default noreverse",
                    "bottom-toolbar.text": "bg:default fg:default noreverse",
                }
            ),
        )

    def _is_bash_mode_active(self) -> bool:
        try:
            text = self._session.default_buffer.text
            return text.startswith(("!", "！"))
        except Exception:
            return False

    def _get_prompt_message(self) -> FormattedText:
        style = INPUT_PROMPT_BASH_STYLE if self._is_bash_mode_active() else INPUT_PROMPT_STYLE
        return FormattedText([(style, self._prompt_text)])

    def _bash_mode_toolbar_fragments(self) -> StyleAndTextTuples:
        if not self._is_bash_mode_active():
            return []
        return [
            ("fg:ansigreen", " bash mode"),
            ("fg:ansibrightblack", " (type ! at start; backspace first char to exit)"),
        ]

    def _setup_model_picker(self) -> None:
        """Initialize the model picker overlay and attach it to the layout."""
        model_picker = SelectOverlay[str](
            pointer="→",
            use_search_filter=True,
            search_placeholder="type to search",
            list_height=20,
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

        # Reserve more vertical space while overlays (selector, completion menu) are open.
        # prompt_toolkit's default multiline prompt caps out at ~9 lines.
        self._patch_prompt_height_for_overlays()

        # Ensure completion menu has default selection
        self._session.default_buffer.on_completions_changed += self._select_first_completion_on_open  # pyright: ignore[reportUnknownMemberType]

    def _patch_prompt_height_for_overlays(self) -> None:
        with contextlib.suppress(Exception):
            root = self._session.app.layout.container
            input_window = _find_window_for_buffer(root, self._session.default_buffer)
            if input_window is None:
                return

            original_height = input_window.height

            # Keep a comfortable multiline editing area even when no completion
            # space is reserved. (We set reserve_space_for_menu=0 to avoid the
            # bottom toolbar jumping when completions open/close.)
            base_rows = 10

            def _height():  # type: ignore[no-untyped-def]
                picker_open = (self._model_picker is not None and self._model_picker.is_open) or (
                    self._thinking_picker is not None and self._thinking_picker.is_open
                )

                try:
                    original_height_value = original_height() if callable(original_height) else original_height
                except Exception:
                    original_height_value = None
                original_min = 0
                if isinstance(original_height_value, Dimension):
                    original_min = int(original_height_value.min)
                elif isinstance(original_height_value, int):
                    original_min = int(original_height_value)

                target_rows = 24 if picker_open else base_rows

                # Cap to the current terminal size.
                # Leave a small buffer to avoid triggering "Window too small".
                try:
                    rows = get_app().output.get_size().rows
                except Exception:
                    rows = 0

                desired = max(original_min, target_rows)
                if rows > 0:
                    desired = max(3, min(desired, rows - 2))

                return Dimension(min=desired, preferred=desired)

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
        result = match_model_from_config()
        if result.error_message or not result.filtered_models:
            return [], None

        items = build_model_select_items(result.filtered_models)

        initial = None
        if self._get_current_model_config_name is not None:
            with contextlib.suppress(Exception):
                initial = self._get_current_model_config_name()
        if initial is None:
            config = load_config()
            initial = config.main_model
        if isinstance(initial, str) and initial and "@" not in initial:
            config = load_config()
            try:
                resolved = config.resolve_model_location_prefer_available(initial) or config.resolve_model_location(
                    initial
                )
            except ValueError:
                resolved = None
            if resolved is not None:
                initial = f"{resolved[0]}@{resolved[1]}"
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
            SelectItem(title=[("class:msg", opt.label + "\n")], value=opt.value, search_text=opt.label)
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
        await self._on_change_thinking(new_thinking)

    # -------------------------------------------------------------------------
    # Bottom toolbar
    # -------------------------------------------------------------------------

    def _get_bottom_toolbar(self) -> FormattedText | None:
        """Return bottom toolbar content.

        This is used inside the prompt_toolkit Application, so avoid printing or
        doing any blocking IO here.
        """
        update_message: str | None = None
        debug_log_path: str | None = None
        if self._status_provider is not None:
            try:
                status = self._status_provider()
                update_message = status.update_message
                debug_log_path = status.debug_log_path
            except (AttributeError, RuntimeError):
                pass

        # Priority: update_message > debug_log_path > shortcut hints
        display_text: str | None = None
        text_style: str = ""
        if update_message:
            display_text = update_message
            text_style = "#ansiyellow"
        elif debug_log_path:
            display_text = f"Debug log: {debug_log_path}"
            text_style = "fg:ansibrightblack"

        bash_frags = self._bash_mode_toolbar_fragments()
        bash_plain = "".join(frag[1] for frag in bash_frags)

        if display_text:
            left_text = " " + display_text
            try:
                terminal_width = shutil.get_terminal_size().columns
            except (OSError, ValueError):
                terminal_width = 0

            if terminal_width > 0 and bash_plain:
                # Keep the right-side bash mode hint visible by truncating the left side if needed.
                reserved = len(bash_plain)
                max_left = max(0, terminal_width - reserved)
                if len(left_text) > max_left:
                    left_text = left_text[: max_left - 1] + "…" if max_left >= 2 else ""
                padding = " " * max(0, terminal_width - len(left_text) - reserved)
            else:
                padding = ""

            return FormattedText([(text_style, left_text + padding), *bash_frags])

        # Show shortcut hints when nothing else to display.
        # In bash mode, prefer showing only the bash hint (no placeholder shortcuts).
        if bash_frags:
            return FormattedText([("fg:default", " "), *bash_frags])
        return self._render_shortcut_hints()

    # -------------------------------------------------------------------------
    # Shortcut hints (bottom toolbar)
    # -------------------------------------------------------------------------

    def _render_shortcut_hints(self) -> FormattedText:
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
                (text_style, " "),
                (symbol_style, "@"),
                (text_style, " files • "),
                (symbol_style, "$"),
                (text_style, " skills • "),
                (symbol_style, "/"),
                (text_style, " commands • "),
                (symbol_style, "!"),
                (text_style, " shell • "),
                (symbol_style, "ctrl-l"),
                (text_style, " models • "),
                (symbol_style, "ctrl-t"),
                (text_style, " think • "),
                (symbol_style, "ctrl-v"),
                (text_style, " paste image"),
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

            # Keep ANSI escape sequences intact while prompt_toolkit is active.
            # This allows Rich-rendered panels (e.g. WelcomeEvent) to display with
            # proper styling instead of showing raw escape codes.
            with patch_stdout(raw=True):
                line: str = await self._session.prompt_async(
                    message=self._get_prompt_message,
                    bottom_toolbar=self._get_bottom_toolbar,
                )
            if self._post_prompt is not None:
                with contextlib.suppress(Exception):
                    self._post_prompt()

            # Expand folded paste markers back into the original content.
            line = expand_paste_markers(line)

            # Convert drag-and-drop file:// URIs that may have bypassed bracketed paste.
            line = convert_dropped_text(line, cwd=Path.cwd())

            # Extract images referenced in the input text
            images = extract_images_from_text(line)

            yield UserInputPayload(text=line, images=images if images else None)

    # Note: Mouse support is intentionally disabled at the PromptSession
    # level so that terminals retain their native scrollback behavior.
