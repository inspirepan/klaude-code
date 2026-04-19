from __future__ import annotations

import asyncio
import contextlib
import re
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from typing import override

import prompt_toolkit.layout.menus as pt_menus
from prompt_toolkit import PromptSession
from prompt_toolkit.application.current import get_app
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.completion import Completion, ThreadedCompleter
from prompt_toolkit.cursor_shapes import CursorShape
from prompt_toolkit.data_structures import Point
from prompt_toolkit.filters import Condition
from prompt_toolkit.formatted_text import FormattedText, StyleAndTextTuples, fragment_list_width, to_formatted_text
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import merge_key_bindings
from prompt_toolkit.layout import Float
from prompt_toolkit.layout.containers import Container, FloatContainer, Window
from prompt_toolkit.layout.controls import BufferControl, UIContent
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.layout.menus import CompletionsMenu, MultiColumnCompletionsMenu
from prompt_toolkit.layout.utils import explode_text_fragments
from prompt_toolkit.patch_stdout import patch_stdout
from prompt_toolkit.styles import Style
from prompt_toolkit.utils import get_cwidth

from klaude_code.app.ports import InputProviderABC
from klaude_code.config import load_config
from klaude_code.config.model_matcher import match_model_from_config
from klaude_code.config.thinking import (
    format_current_thinking,
    get_thinking_picker_data,
    parse_thinking_value,
)
from klaude_code.protocol import llm_param
from klaude_code.protocol.message import UserInputPayload
from klaude_code.tui.command.types import CommandInfo
from klaude_code.tui.components.user_input import USER_MESSAGE_MARK
from klaude_code.tui.input.completers import AT_TOKEN_PATTERN, SKILL_TOKEN_PATTERN, create_repl_completer
from klaude_code.tui.input.drag_drop import convert_dropped_text
from klaude_code.tui.input.images import (
    capture_clipboard_tag,
    extract_images_from_text,
    has_clipboard_image,
)
from klaude_code.tui.input.key_bindings import create_key_bindings
from klaude_code.tui.input.paste import expand_paste_markers, expand_paste_markers_with_file_save
from klaude_code.tui.terminal.selector import SelectItem, SelectOverlay, build_model_select_items

COMPLETION_SELECTED_BG = "ansigreen"
COMPLETION_MENU = "ansibrightblack"
INPUT_PROMPT_STYLE = "ansimagenta bold"
INPUT_PROMPT_BASH_STYLE = "ansigreen"
COMPLETION_TRUNCATION_SYMBOL = "…"

_REMOTE_URL_RE = re.compile(r"(?:.*[:/])([^/]+)/([^/]+?)(?:\.git)?$")

def _get_git_info() -> tuple[str | None, str | None]:
    """Return (repo_display, branch) by reading .git directly, no subprocess.

    repo_display is "org/repo" parsed from the origin remote URL, or None.
    branch is the current branch name, or None for detached HEAD / non-git.
    """
    cwd = Path.cwd()
    for directory in [cwd, *cwd.parents]:
        git_path = directory / ".git"
        if not git_path.exists():
            continue
        try:
            if git_path.is_file():
                text = git_path.read_text().strip()
                if text.startswith("gitdir: "):
                    resolved = text[8:]
                    git_path = Path(resolved) if Path(resolved).is_absolute() else (directory / resolved).resolve()

            # Branch from HEAD
            branch: str | None = None
            head = (git_path / "HEAD").read_text().strip()
            if head.startswith("ref: refs/heads/"):
                branch = head[16:]

            # Repo name from origin remote URL in config
            repo_display: str | None = None
            config_file = git_path / "config"
            if config_file.is_file():
                in_origin = False
                for line in config_file.read_text().splitlines():
                    stripped = line.strip()
                    if stripped == '[remote "origin"]':
                        in_origin = True
                    elif stripped.startswith("["):
                        in_origin = False
                    elif in_origin and stripped.startswith("url = "):
                        m = _REMOTE_URL_RE.match(stripped[6:].strip())
                        if m:
                            repo_display = f"{m.group(1)}/{m.group(2)}"
                        break

            return repo_display, branch
        except Exception:
            pass
        return None, None
    return None, None

def _trim_formatted_text_with_ellipsis(
    formatted_text: StyleAndTextTuples,
    max_width: int,
) -> tuple[StyleAndTextTuples, int]:
    """Trim completion text and use a single unicode ellipsis on overflow."""

    width = fragment_list_width(formatted_text)
    if width <= max_width:
        return formatted_text, width

    if max_width <= 0:
        return [], 0

    ellipsis_width = get_cwidth(COMPLETION_TRUNCATION_SYMBOL)
    remaining_width = max(0, max_width - ellipsis_width)
    result: StyleAndTextTuples = []

    for style_and_ch in explode_text_fragments(formatted_text):
        ch_width = get_cwidth(style_and_ch[1])
        if ch_width <= remaining_width:
            result.append(style_and_ch)
            remaining_width -= ch_width
            continue
        break

    result.append(("", COMPLETION_TRUNCATION_SYMBOL))
    used_width = max_width - remaining_width
    return result, used_width

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

def _strip_dim_fg(fragments: StyleAndTextTuples) -> StyleAndTextTuples:
    """Strip 'ansibrightblack' (dim directory color) so the selection foreground takes effect."""
    result: StyleAndTextTuples = []
    for item in fragments:
        style = item[0]
        if "ansibrightblack" in style:
            style = style.replace("ansibrightblack", "").strip()
        result.append((style, item[1], *item[2:]))  # type: ignore[arg-type]
    return result

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
        text, text_width = _trim_formatted_text_with_ellipsis(completion.display, max_text_width)
        padding = " " * (width - self._PREFIX_WIDTH - text_width)

        if is_current_completion:
            text = _strip_dim_fg(text)

        return to_formatted_text(
            [("", prefix), *text, ("", padding)],
            style=style_str,
        )

    @override
    def _get_menu_item_meta_fragments(
        self,
        completion: Completion,
        is_current_completion: bool,
        width: int,
    ) -> StyleAndTextTuples:
        if is_current_completion:
            style_str = "class:completion-menu.meta.completion.current"
        else:
            style_str = "class:completion-menu.meta.completion"

        text, text_width = _trim_formatted_text_with_ellipsis(completion.display_meta, width - 2)
        padding = " " * (width - 1 - text_width)
        return to_formatted_text(
            [("", " "), *text, ("", padding)],
            style=style_str,
        )

# ---------------------------------------------------------------------------
# PromptToolkitInput
# ---------------------------------------------------------------------------

class PromptToolkitInput(InputProviderABC):
    def __init__(
        self,
        prompt: str = USER_MESSAGE_MARK,
        pre_prompt: Callable[[], None] | None = None,
        post_prompt: Callable[[], None] | None = None,
        on_prompt_start: Callable[[], None] | None = None,
        on_prompt_end: Callable[[], None] | None = None,
        on_user_activity: Callable[[], None] | None = None,
        on_change_model: Callable[[str], Awaitable[None]] | None = None,
        get_current_model_config_name: Callable[[], str | None] | None = None,
        on_change_thinking: Callable[[llm_param.Thinking], Awaitable[None]] | None = None,
        get_current_llm_config: Callable[[], llm_param.LLMConfigParameter | None] | None = None,
        command_info_provider: Callable[[], list[CommandInfo]] | None = None,
    ):
        self._prompt_text = prompt
        self._pre_prompt = pre_prompt
        self._post_prompt = post_prompt
        self._on_prompt_start = on_prompt_start
        self._on_prompt_end = on_prompt_end
        self._on_user_activity = on_user_activity
        self._on_change_model = on_change_model
        self._get_current_model_config_name = get_current_model_config_name
        self._on_change_thinking = on_change_thinking
        self._get_current_llm_config = get_current_llm_config
        self._command_info_provider = command_info_provider
        self._next_prefill_text: str | None = None
        self._session_dir: Path | None = None
        self._clipboard_has_image: bool = False
        self._clipboard_watcher_task: asyncio.Task[None] | None = None

        self._session = self._build_prompt_session(prompt)
        self._session.app.key_processor.before_key_press += self._handle_user_activity
        self._setup_model_picker()
        self._setup_thinking_picker()
        self._apply_layout_customizations()

    def _handle_user_activity(self, _sender: object) -> None:
        if self._on_user_activity is not None:
            self._on_user_activity()

    def set_next_prefill(self, text: str | None) -> None:
        self._next_prefill_text = text

    def set_session_dir(self, session_dir: Path | None) -> None:
        self._session_dir = session_dir

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
            skill_token_pattern=SKILL_TOKEN_PATTERN,
            input_enabled=input_enabled,
            open_model_picker=self._open_model_picker,
            open_thinking_picker=self._open_thinking_picker,
        )

        completion_selected = COMPLETION_SELECTED_BG

        return PromptSession(
            # Use a stable prompt string; we override the style dynamically in prompt_async.
            [(INPUT_PROMPT_STYLE, prompt)],
            history=FileHistory(str(history_path)),
            multiline=True,
            cursor=CursorShape.BLINKING_BEAM,
            key_bindings=kb,
            completer=ThreadedCompleter(create_repl_completer(command_info_provider=self._command_info_provider)),
            complete_while_typing=True,
            # Avoid reserving extra rows for completion menus in non-fullscreen mode.
            reserve_space_for_menu=0,
            erase_when_done=True,
            mouse_support=False,
            prompt_continuation="  ",
            placeholder=self._build_placeholder,
            rprompt=self._get_rprompt_message,
            style=Style.from_dict(
                {
                    "placeholder": "fg:ansibrightblack italic",
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
                    "search_prefix": "ansibrightblack",
                    "search_placeholder": "fg:ansibrightblack italic",
                    "search_input": "",
                    "search_success": "noinherit fg:ansigreen",
                    "search_none": "noinherit fg:ansired",
                }
            ),
        )

    def _build_placeholder(self) -> FormattedText:
        """Build placeholder showing repo/directory name and Git branch.

        When an image is detected on the system clipboard, replace the hint
        with a ctrl+v paste reminder instead.
        """
        if self._clipboard_has_image:
            return FormattedText([("class:placeholder", "   ctrl+v to paste image")])

        repo_display, branch = _get_git_info()
        cwd_name = Path.cwd().name or str(Path.cwd())
        dir_name = repo_display or cwd_name

        parts = [dir_name]
        # Show cwd in brackets when it differs from the repo name
        if repo_display and cwd_name != repo_display.rsplit("/", 1)[-1]:
            parts.append(f"[{cwd_name}]")
        if branch:
            parts.append(f"({branch})")

        text = " ".join(parts)
        return FormattedText([("class:placeholder", f"   {text}")])

    def _is_bash_mode_active(self) -> bool:
        try:
            text = self._session.default_buffer.text
            return text.startswith(("!", "！"))
        except Exception:
            return False

    def _get_prompt_message(self) -> FormattedText:
        return FormattedText([(INPUT_PROMPT_STYLE, self._prompt_text)])

    def _get_rprompt_message(self) -> FormattedText:
        if not self._is_bash_mode_active():
            return FormattedText([])
        return FormattedText([(INPUT_PROMPT_BASH_STYLE, "(bash mode)")])

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
            # space is reserved.
            # Also allow the input area to grow with content so that large multi-line
            # inputs expand the prompt instead of scrolling within a fixed-height window.
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

                try:
                    buffer_line_count = int(self._session.default_buffer.document.line_count)
                except Exception:
                    buffer_line_count = 1

                # Grow with content (based on newline count), but keep a sensible minimum.
                content_rows = max(1, buffer_line_count)
                target_rows = max(base_rows, content_rows)

                # When a picker overlay is open, keep enough height for it to be usable.
                if picker_open:
                    target_rows = max(target_rows, 24)

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
    # Clipboard image watcher
    # -------------------------------------------------------------------------

    # Poll interval for the clipboard image check. Each poll spawns an
    # `osascript` on macOS (or equivalent on other platforms), so keep it
    # conservative.
    _CLIPBOARD_POLL_INTERVAL = 3.0

    async def _watch_clipboard_image(self) -> None:
        """Periodically refresh `self._clipboard_has_image`.

        Only polls while the input buffer is empty (the only time the
        placeholder is actually rendered). Invalidates the app when the state
        flips so the placeholder re-renders immediately.
        """
        while True:
            try:
                buffer_empty = not self._session.default_buffer.text
            except Exception:
                buffer_empty = False

            has_image = False
            if buffer_empty:
                try:
                    has_image = await asyncio.to_thread(has_clipboard_image)
                except Exception:
                    has_image = False

            if has_image != self._clipboard_has_image:
                self._clipboard_has_image = has_image
                with contextlib.suppress(Exception):
                    self._session.app.invalidate()

            await asyncio.sleep(self._CLIPBOARD_POLL_INTERVAL)

    def _ensure_clipboard_watcher(self) -> None:
        if self._clipboard_watcher_task is not None and not self._clipboard_watcher_task.done():
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._clipboard_watcher_task = loop.create_task(self._watch_clipboard_image())

    def _cancel_clipboard_watcher(self) -> None:
        task = self._clipboard_watcher_task
        if task is None:
            return
        self._clipboard_watcher_task = None
        if not task.done():
            task.cancel()

    # -------------------------------------------------------------------------
    # InputProviderABC implementation
    # -------------------------------------------------------------------------

    async def start(self) -> None:
        self._ensure_clipboard_watcher()

    async def stop(self) -> None:
        self._cancel_clipboard_watcher()

    @override
    async def iter_inputs(self) -> AsyncIterator[UserInputPayload]:
        while True:
            if self._pre_prompt is not None:
                with contextlib.suppress(Exception):
                    self._pre_prompt()

            # Keep ANSI escape sequences intact while prompt_toolkit is active.
            # This allows Rich-rendered panels (e.g. WelcomeEvent) to display with
            # proper styling instead of showing raw escape codes.
            if self._on_prompt_start is not None:
                with contextlib.suppress(Exception):
                    self._on_prompt_start()
            try:
                with patch_stdout(raw=True):
                    default_text = self._next_prefill_text
                    self._next_prefill_text = None
                    if default_text is None:
                        line = await self._session.prompt_async(message=self._get_prompt_message)
                    else:
                        line = await self._session.prompt_async(message=self._get_prompt_message, default=default_text)
            finally:
                if self._on_prompt_end is not None:
                    with contextlib.suppress(Exception):
                        self._on_prompt_end()
            if self._post_prompt is not None:
                with contextlib.suppress(Exception):
                    self._post_prompt()

            # Expand folded paste markers back into the original content.
            # Save large pastes to files when session directory is available.
            pasted_files: dict[str, str] | None = None
            if self._session_dir is not None:
                line, pasted_file_map = expand_paste_markers_with_file_save(line, self._session_dir)
                pasted_files = pasted_file_map or None
            else:
                line = expand_paste_markers(line)

            # Convert drag-and-drop file:// URIs that may have bypassed bracketed paste.
            line = convert_dropped_text(line, cwd=Path.cwd())

            # Extract images referenced in the input text
            images = extract_images_from_text(line)

            yield UserInputPayload(text=line, images=images if images else None, pasted_files=pasted_files)

    # Note: Mouse support is intentionally disabled at the PromptSession
    # level so that terminals retain their native scrollback behavior.
