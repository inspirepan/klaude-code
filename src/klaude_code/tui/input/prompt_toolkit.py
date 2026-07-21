from __future__ import annotations

import asyncio
import contextlib
import re
import sys
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from typing import override

from prompt_toolkit import PromptSession
from prompt_toolkit.application.current import get_app
from prompt_toolkit.buffer import Buffer, CompletionState
from prompt_toolkit.completion import Completion, ThreadedCompleter
from prompt_toolkit.cursor_shapes import CursorShape
from prompt_toolkit.filters import Condition
from prompt_toolkit.formatted_text import FormattedText, StyleAndTextTuples, to_plain_text
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import merge_key_bindings
from prompt_toolkit.layout.containers import ConditionalContainer, Container, HSplit, Window
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.output.color_depth import ColorDepth
from prompt_toolkit.utils import get_cwidth

from klaude_code.app.ports import InputProviderABC
from klaude_code.config import load_config
from klaude_code.config.model_matcher import match_model_from_config
from klaude_code.protocol.message import UserInputPayload
from klaude_code.tui.command.types import CommandInfo
from klaude_code.tui.commands import PromptStatusLine
from klaude_code.tui.components.user_input import USER_MESSAGE_MARK
from klaude_code.tui.input.completers import AT_TOKEN_PATTERN, SKILL_TOKEN_PATTERN, create_repl_completer
from klaude_code.tui.input.completion_menu import (
    build_completion_panel_fragments,
    customize_completion_menus,
    remove_completion_menu_floats,
)
from klaude_code.tui.input.csi_u import KITTY_KEYBOARD_RESET, install_csi_u_sequences
from klaude_code.tui.input.drag_drop import convert_dropped_text
from klaude_code.tui.input.flicker_safe_stdout import flicker_safe_patch_stdout
from klaude_code.tui.input.images import (
    capture_clipboard_tag,
    extract_images_from_text,
    has_clipboard_image,
)
from klaude_code.tui.input.key_bindings import create_key_bindings
from klaude_code.tui.input.paste import (
    expand_paste_markers,
    expand_paste_markers_for_history,
    expand_paste_markers_with_file_save,
)
from klaude_code.tui.input.prompt_status_bar import PromptBottomBar
from klaude_code.tui.input.pt_theme import CLASS_LINES, CLASS_META, CLASS_METADATA_FOOTER, get_base_style
from klaude_code.tui.terminal.selector import SelectItem, SelectOverlay, build_model_select_items

# Style class tokens used by the REPL prompt. The concrete colors live in
# ``pt_theme.py`` so that hex values follow the resolved light/dark palette.
INPUT_PROMPT_STYLE = "class:prompt"
INPUT_PROMPT_RUNNING_STYLE = "class:prompt.running"
INPUT_PROMPT_BASH_STYLE = "class:prompt.bash"
_INPUT_HEIGHT_SAFETY_ROWS = 1

_REMOTE_URL_RE = re.compile(r"(?:.*[:/])([^/]+)/([^/]+?)(?:\.git)?$")

# The prompt footer is re-rendered on every frame (spinner runs at ~8fps while
# an agent streams). Reading .git/HEAD and .git/config from disk each frame is
# wasted event-loop time; branch switches are rare, so cache with a short TTL.
_GIT_INFO_CACHE_TTL_S = 5.0
_git_info_cache: tuple[float, Path, tuple[str | None, str | None]] | None = None


class _PromptPaused(Exception):
    """Internal signal used to pause the REPL while another prompt_toolkit app owns stdin."""


def _get_git_info_cached() -> tuple[str | None, str | None]:
    """TTL-cached wrapper around :func:`_get_git_info`, keyed by cwd."""
    global _git_info_cache
    now = time.monotonic()
    cwd = Path.cwd()
    if _git_info_cache is not None:
        cached_at, cached_cwd, cached_info = _git_info_cache
        if cached_cwd == cwd and now - cached_at < _GIT_INFO_CACHE_TTL_S:
            return cached_info
    info = _get_git_info()
    _git_info_cache = (now, cwd, info)
    return info


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


# ---------------------------------------------------------------------------
# Layout helpers
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# History helpers
# ---------------------------------------------------------------------------


class _PasteAwareFileHistory(FileHistory):
    """Store expanded paste content so recalled history entries stay reusable."""

    @override
    def append_string(self, string: str) -> None:
        super().append_string(expand_paste_markers_for_history(string))


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
        get_current_model_provider_name: Callable[[], str | None] | None = None,
        command_info_provider: Callable[[], list[CommandInfo]] | None = None,
        dequeue_pending_messages: Callable[[], tuple[str, ...]] | None = None,
        request_interrupt: Callable[[], None] | None = None,
        refresh_status: Callable[[], None] | None = None,
    ):
        self._prompt_text = prompt
        self._pre_prompt = pre_prompt
        self._post_prompt = post_prompt
        self._on_prompt_start = on_prompt_start
        self._on_prompt_end = on_prompt_end
        self._on_user_activity = on_user_activity
        self._on_change_model = on_change_model
        self._get_current_model_config_name = get_current_model_config_name
        self._get_current_model_provider_name = get_current_model_provider_name
        self._command_info_provider = command_info_provider
        self._dequeue_pending_messages = dequeue_pending_messages
        self._request_interrupt = request_interrupt
        self._refresh_status = refresh_status
        self._next_prefill_text: str | None = None
        self._session_dir: Path | None = None
        self._clipboard_has_image: bool = False
        self._clipboard_watcher_task: asyncio.Task[None] | None = None
        self._prompt_suggestion: str | None = None
        self._last_completion_panel_completions: tuple[Completion, ...] = ()
        self._last_completion_panel_selected_index: int | None = None
        self._last_completion_panel_context_key: str | None = None
        self._completion_panel_snapshot_cache: (
            tuple[tuple[int, int, int | None, str], tuple[list[Completion], int | None]] | None
        ) = None
        self._queued_edit_active = False
        self._agent_running = False
        self._prompt_active = False
        self._prompt_pause_waiter: asyncio.Future[None] | None = None
        self._external_input_pause_count = 0
        self._external_input_resume_event = asyncio.Event()
        self._external_input_resume_event.set()

        self._bottom_bar = PromptBottomBar(
            invalidate=self._invalidate_app,
            refresh_status=refresh_status,
            is_agent_running=self._is_agent_running,
        )

        # Teach the vt100 parser kitty CSI-u key encodings before any input is
        # parsed, so a leaked kitty keyboard mode cannot turn Ctrl+<key> into a
        # task-interrupting Escape plus garbage text.
        install_csi_u_sequences()

        self._session = self._build_prompt_session(prompt)
        self._session.app.key_processor.before_key_press += self._handle_user_activity
        self._setup_model_picker()
        self._apply_layout_customizations()

    def _handle_user_activity(self, _sender: object) -> None:
        if self._on_user_activity is not None:
            self._on_user_activity()

    def set_next_prefill(self, text: str | None) -> None:
        self._next_prefill_text = text
        if not text or not self._prompt_active or self._is_agent_running():
            return
        with contextlib.suppress(Exception):
            if self._session.default_buffer.text:
                return
        with contextlib.suppress(Exception):
            self._session.app.exit(exception=_PromptPaused())

    def set_session_dir(self, session_dir: Path | None) -> None:
        self._session_dir = session_dir

    def set_stream_lines(self, lines: tuple[str, ...], *, end_of_stream: bool = False) -> None:
        self._bottom_bar.set_stream_lines(lines, end_of_stream=end_of_stream)

    def set_status_lines(self, lines: tuple[PromptStatusLine, ...], *, separator_text: str | None = None) -> None:
        self._bottom_bar.set_status_lines(lines, separator_text=separator_text)

    def set_pending_messages(self, messages: tuple[str, ...]) -> None:
        self._bottom_bar.set_pending_messages(messages)

    def set_agent_running(self, running: bool) -> None:
        if self._agent_running == running:
            return
        self._agent_running = running
        self._invalidate_app()

    def set_startup_loading(self, loading: bool) -> None:
        self._bottom_bar.set_startup_loading(loading)

    def _invalidate_app(self) -> None:
        with contextlib.suppress(Exception):
            self._session.app.invalidate()

    def set_dequeue_pending_messages(self, dequeue_pending_messages: Callable[[], tuple[str, ...]] | None) -> None:
        self._dequeue_pending_messages = dequeue_pending_messages

    def set_interrupt_handler(self, request_interrupt: Callable[[], None] | None) -> None:
        if request_interrupt is self._request_interrupt:
            return
        self._request_interrupt = request_interrupt
        self._invalidate_app()

    async def pause_for_external_input(self) -> Callable[[], None]:
        """Pause the active REPL prompt so a modal selector can read stdin exclusively."""

        self._external_input_pause_count += 1
        self._external_input_resume_event.clear()

        def _resume() -> None:
            self._external_input_pause_count = max(0, self._external_input_pause_count - 1)
            if self._external_input_pause_count == 0:
                self._external_input_resume_event.set()

        if not self._prompt_active:
            return _resume
        if self._prompt_pause_waiter is not None:
            await self._prompt_pause_waiter
            return _resume

        loop = asyncio.get_running_loop()
        waiter: asyncio.Future[None] = loop.create_future()
        self._prompt_pause_waiter = waiter
        with contextlib.suppress(Exception):
            text = self._session.default_buffer.text
            self._next_prefill_text = text or None
        try:
            self._session.app.exit(exception=_PromptPaused())
        except Exception:
            self._prompt_pause_waiter = None
            if not waiter.done():
                waiter.set_result(None)
            return _resume
        await waiter
        return _resume

    @override
    def set_prompt_suggestion(self, text: str | None) -> None:
        """Update the predicted-next-prompt state and repaint the placeholder.

        When ``text`` is set and the buffer is empty, the placeholder shows the
        suggestion and pressing Enter submits it / Tab fills the buffer for
        editing (see ``key_bindings.py``).
        """
        normalized = text.strip() if isinstance(text, str) else None
        self._prompt_suggestion = normalized or None
        with contextlib.suppress(Exception):
            self._session.app.invalidate()

    def _get_prompt_suggestion(self) -> str | None:
        return self._prompt_suggestion

    def _consume_prompt_suggestion(self) -> str | None:
        suggestion = self._prompt_suggestion
        self._prompt_suggestion = None
        return suggestion

    def _build_prompt_session(self, prompt: str) -> PromptSession[str]:
        """Build the prompt_toolkit PromptSession with key bindings and styles."""
        project = str(Path.cwd()).strip("/").replace("/", "-")
        history_path = Path.home() / ".klaude" / "projects" / project / "input" / "input_history.txt"
        history_path.parent.mkdir(parents=True, exist_ok=True)
        history_path.touch(exist_ok=True)

        # The model picker will be set up later; create placeholder condition.
        self._model_picker: SelectOverlay[str] | None = None
        input_enabled = Condition(lambda: self._model_picker is None or not self._model_picker.is_open)

        kb = create_key_bindings(
            capture_clipboard_tag=capture_clipboard_tag,
            at_token_pattern=AT_TOKEN_PATTERN,
            skill_token_pattern=SKILL_TOKEN_PATTERN,
            input_enabled=input_enabled,
            open_model_picker=self._open_model_picker,
            get_prompt_suggestion=self._get_prompt_suggestion,
            consume_prompt_suggestion=self._consume_prompt_suggestion,
            dequeue_pending_messages=lambda: (
                self._dequeue_pending_messages() if self._dequeue_pending_messages is not None else ()
            ),
            mark_dequeued_messages_for_edit=self._mark_queued_edit_active,
            has_pending_messages=lambda: self._bottom_bar.has_pending_messages,
            request_interrupt=lambda: self._request_interrupt() if self._request_interrupt is not None else None,
            is_interrupt_available=lambda: self._request_interrupt is not None,
        )

        return PromptSession(
            # Use a stable prompt string; we override the style dynamically in prompt_async.
            [(INPUT_PROMPT_STYLE, prompt)],
            history=_PasteAwareFileHistory(str(history_path)),
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
            # Force 24-bit color so hex styles render exactly as specified
            # instead of being snapped to the xterm-256 palette.
            color_depth=ColorDepth.TRUE_COLOR,
            # Pull the shared theme so hex colors here match the rich UI.
            style=get_base_style(),
        )

    def _build_placeholder(self) -> FormattedText:
        """Build placeholder showing repo/directory name, Git branch, and model.

        When a prompt suggestion is pending, show it with an accept hint.
        When an image is detected on the system clipboard, also show a ctrl+v
        paste reminder.
        """
        if self._is_agent_running():
            text = "   Queue a follow-up"
            if self._clipboard_has_image:
                text = f"{text} · ctrl+v to paste image"
            return FormattedText([("class:placeholder", text)])

        if self._prompt_suggestion:
            hint = "[enter send · tab edit]"
            if self._clipboard_has_image:
                hint = f"{hint} · ctrl+v to paste image"
            suggestion = self._prompt_suggestion
            try:
                cols = get_app().output.get_size().columns
            except Exception:
                cols = 80
            # Available width for placeholder = terminal width - prompt mark width.
            prompt_width = get_cwidth(self._prompt_text)
            used = get_cwidth(suggestion) + get_cwidth(hint)
            padding = max(1, cols - prompt_width - used)
            parts: StyleAndTextTuples = [
                ("class:prompt-suggestion", suggestion),
                ("class:placeholder-hint", " " * padding + hint),
            ]
            return FormattedText(parts)

        if self._clipboard_has_image:
            return FormattedText([("class:placeholder", "   ctrl+v to paste image")])

        return FormattedText([])

    def _build_prompt_context_fragments(self, *, prefix: str = "") -> StyleAndTextTuples:
        """Build the idle prompt context shown below the input frame."""

        repo_display, branch = _get_git_info_cached()
        cwd_name = Path.cwd().name or str(Path.cwd())
        dir_name = repo_display or cwd_name
        current_model: str | None = None
        if self._get_current_model_config_name is not None:
            with contextlib.suppress(Exception):
                current_model = self._get_current_model_config_name()
        if not current_model:
            with contextlib.suppress(Exception):
                config = load_config()
                main_candidates = config.iter_model_config_candidates(config.main_model)
                current_model = main_candidates[0].selector if main_candidates else None
        model_name = current_model.split("@", 1)[0] if current_model else None
        provider_name: str | None = None
        if self._get_current_model_provider_name is not None:
            with contextlib.suppress(Exception):
                provider_name = self._get_current_model_provider_name()

        parts = [dir_name]
        # Show cwd in brackets when it differs from the repo name
        if repo_display and cwd_name != repo_display.rsplit("/", 1)[-1]:
            parts.append(f"[{cwd_name}]")
        if branch:
            parts.append(f"({branch})")

        suffix = ""
        if len(parts) > 1:
            suffix = " " + " ".join(parts[1:])
        if not model_name:
            return [("class:placeholder", prefix), ("class:accent.blue", dir_name), ("class:placeholder", suffix)]
        fragments: StyleAndTextTuples = [
            ("class:placeholder", prefix),
            ("class:accent.blue", dir_name),
            ("class:placeholder", f"{suffix} > "),
            ("class:accent.blue", model_name),
        ]
        if provider_name:
            fragments.extend([(CLASS_META, " via "), (CLASS_META, provider_name)])
        return fragments

    def _is_bash_mode_active(self) -> bool:
        try:
            text = self._session.default_buffer.text
            return text.startswith(("!", "！"))
        except Exception:
            return False

    def _is_agent_running(self) -> bool:
        return self._agent_running

    def _take_next_prefill_text(self) -> str | None:
        if self._is_agent_running():
            return None
        text = self._next_prefill_text
        self._next_prefill_text = None
        return text

    def _get_prompt_message(self) -> FormattedText:
        style = INPUT_PROMPT_RUNNING_STYLE if self._is_agent_running() else INPUT_PROMPT_STYLE
        return FormattedText([(style, self._prompt_text)])

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

    def _apply_layout_customizations(self) -> None:
        """Apply layout customizations after session is created."""
        # Make the Escape key feel responsive
        with contextlib.suppress(Exception):
            self._session.app.ttimeoutlen = 0.05

        # Pace redraws so the invalidate storm while an agent streams
        # (spinner frames + stream tail + status lines each call invalidate)
        # coalesces into at most ~50fps instead of one full render per event.
        with contextlib.suppress(Exception):
            self._session.app.min_redraw_interval = 0.02

        # Keep completion popups left-aligned and customize completion rendering.
        with contextlib.suppress(Exception):
            customize_completion_menus(self._session.app.layout.container)
            remove_completion_menu_floats(self._session.app.layout.container)

        # Reserve more vertical space while overlays (selector, completion menu) are open.
        # prompt_toolkit's default multiline prompt caps out at ~9 lines.
        self._patch_prompt_height_for_overlays()

        # Ensure completion menu has default selection
        self._session.default_buffer.on_completions_changed += self._select_first_completion_on_open  # pyright: ignore[reportUnknownMemberType]

        self._install_bottom_windows()

    def _install_bottom_windows(self) -> None:
        with contextlib.suppress(Exception):
            root = self._session.app.layout.container
            bar_containers = self._bottom_bar.build_containers()
            input_top_rule = Window(
                content=FormattedTextControl(self._get_input_top_rule_fragments),
                height=1,
                dont_extend_height=True,
            )
            input_bottom_rule = Window(
                content=FormattedTextControl(self._get_input_bottom_rule_fragments),
                height=1,
                dont_extend_height=True,
            )
            completion_panel = Window(
                content=FormattedTextControl(self._get_completion_panel_fragments),
                height=self._get_completion_panel_height,
                dont_extend_height=True,
            )
            input_footer = Window(
                content=FormattedTextControl(self._get_input_footer_fragments),
                height=self._get_input_footer_height,
                dont_extend_height=True,
            )
            dynamic_panels: list[Container] = [
                ConditionalContainer(completion_panel, filter=Condition(self._is_completion_panel_visible))
            ]
            if self._model_picker is not None:
                dynamic_panels.append(self._model_picker.container)
            self._session.app.layout.container = HSplit(
                [*bar_containers, input_top_rule, root, input_bottom_rule, *dynamic_panels, input_footer]
            )

    def _get_input_top_rule_fragments(self) -> StyleAndTextTuples:
        return self._get_input_bottom_rule_fragments()

    def _get_input_bottom_rule_fragments(self) -> StyleAndTextTuples:
        try:
            columns = get_app().output.get_size().columns
        except Exception:
            columns = 80
        return [(CLASS_LINES, "─" * max(1, columns))]

    def _get_input_footer_fragments(self) -> StyleAndTextTuples:
        if self._is_completion_active() or self._is_completion_panel_visible() or self._is_picker_open():
            return []
        fragments = self._build_prompt_context_fragments(prefix="  ")
        status_hint = self._bottom_bar.running_separator_label
        if status_hint:
            fragments.extend([(CLASS_META, " · "), (CLASS_META, status_hint)])
        for line in self._bottom_bar.metadata_footer_lines:
            fragments.extend([("", "\n"), (CLASS_METADATA_FOOTER, f"  {line}")])
        return fragments

    def _get_input_footer_height(self) -> int:
        if self._is_completion_active() or self._is_completion_panel_visible() or self._is_picker_open():
            return 1
        return 1 + max(1, len(self._bottom_bar.metadata_footer_lines))

    def _is_picker_open(self) -> bool:
        return self._model_picker is not None and self._model_picker.is_open

    def _is_completion_active(self) -> bool:
        try:
            return (
                self._session.default_buffer.complete_state is not None
                and self._current_completion_context() is not None
            )
        except Exception:
            return False

    def _is_completion_panel_visible(self) -> bool:
        completions, _selected_index = self._get_completion_panel_snapshot()
        return bool(completions)

    def _get_completion_panel_snapshot(self) -> tuple[list[Completion], int | None]:
        try:
            state = self._session.default_buffer.complete_state
            text_before = self._session.default_buffer.document.text_before_cursor
        except Exception:
            return [], None
        if state is None:
            return [], None
        # This snapshot is requested several times per rendered frame
        # (visibility filter, window height, fragments, reserved input rows),
        # and the cached-panel fallback below runs to_plain_text over every
        # completion entry. Memoize per (state, selection, input) key so each
        # distinct UI state pays the cost once. The completion count is part
        # of the key because ThreadedCompleter appends to the same
        # CompletionState in place while results stream in.
        cache_key = (id(state), len(state.completions), getattr(state, "complete_index", None), text_before)
        cached_snapshot = self._completion_panel_snapshot_cache
        if cached_snapshot is not None and cached_snapshot[0] == cache_key:
            return cached_snapshot[1]
        snapshot = self._compute_completion_panel_snapshot(state)
        self._completion_panel_snapshot_cache = (cache_key, snapshot)
        return snapshot

    def _compute_completion_panel_snapshot(self, state: CompletionState) -> tuple[list[Completion], int | None]:
        if state.completions:
            completions = list(state.completions)
            context = self._current_completion_context()
            if context is not None:
                self._last_completion_panel_completions = tuple(completions)
                self._last_completion_panel_selected_index = state.complete_index
                self._last_completion_panel_context_key = context[0]
            return completions, state.complete_index

        cached = self._filter_cached_completion_panel()
        if not cached:
            return [], None
        selected_index = self._last_completion_panel_selected_index
        if selected_index is not None:
            selected_index = max(0, min(selected_index, len(cached) - 1))
        return cached, selected_index

    def _filter_cached_completion_panel(self) -> list[Completion]:
        cached = list(self._last_completion_panel_completions)
        if not cached:
            return []

        context = self._current_completion_context()
        if context is None:
            return []
        context_key, fragment = context
        if context_key != self._last_completion_panel_context_key:
            return []
        if not fragment:
            return cached

        result: list[Completion] = []
        for completion in cached:
            display_text = to_plain_text(completion.display)
            meta_text = to_plain_text(completion.display_meta)
            haystack = f"{completion.text} {display_text} {meta_text}".lower()
            if fragment in haystack:
                result.append(completion)
        return result

    def _current_completion_context(self) -> tuple[str, str] | None:
        try:
            document = self._session.default_buffer.document
            text_before = document.text_before_cursor
            line_before = document.current_line_before_cursor
        except Exception:
            return None

        slash_match = re.search(r"^\s*(?P<prefix>//|/)(?P<frag>[^\s/]*)$", line_before)
        if slash_match and self._is_current_line_at_effective_start(text_before):
            prefix = slash_match.group("prefix")
            return f"slash:{prefix}", slash_match.group("frag").lower()

        skill_match = SKILL_TOKEN_PATTERN.search(line_before)
        if skill_match:
            prefix = skill_match.group("prefix")
            return f"skill:{prefix}", skill_match.group("frag").lower()

        at_match = AT_TOKEN_PATTERN.search(text_before)
        if at_match:
            frag = at_match.group("frag")
            if frag.startswith('"'):
                frag = frag[1:]
                if frag.endswith('"'):
                    frag = frag[:-1]
            return "at", frag.lower()

        return None

    def _is_current_line_at_effective_start(self, text_before: str) -> bool:
        last_newline = text_before.rfind("\n")
        preceding = "" if last_newline < 0 else text_before[: last_newline + 1]
        return preceding.strip() == ""

    def _get_completion_panel_height(self) -> int:
        completions, _selected_index = self._get_completion_panel_snapshot()
        if not completions:
            return 0
        return min(10, len(completions))

    def _get_completion_panel_fragments(self) -> StyleAndTextTuples:
        completions, selected_index = self._get_completion_panel_snapshot()
        if not completions:
            return []
        try:
            columns = get_app().output.get_size().columns
        except Exception:
            columns = 80
        return build_completion_panel_fragments(
            completions,
            selected_index=selected_index,
            width=columns,
            max_height=10,
        )

    def _patch_prompt_height_for_overlays(self) -> None:
        with contextlib.suppress(Exception):
            root = self._session.app.layout.container
            input_window = _find_window_for_buffer(root, self._session.default_buffer)
            if input_window is None:
                return

            original_height = input_window.height

            # Keep the idle prompt compact. Grow only with multiline input;
            # completions and selectors render below the input frame.
            base_rows = 1

            def _height():  # type: ignore[no-untyped-def]
                try:
                    original_height_value = original_height() if callable(original_height) else original_height  # ty: ignore[call-top-callable]
                except Exception:
                    original_height_value = None
                original_min = 0
                if isinstance(original_height_value, Dimension):
                    original_min = int(original_height_value.min)
                elif isinstance(original_height_value, int):
                    original_min = int(original_height_value)

                try:
                    size = get_app().output.get_size()
                    rows = size.rows
                    columns = size.columns
                except Exception:
                    rows = 0
                    columns = 80

                # Grow with content, counting both explicit newlines and soft wraps.
                content_rows = self._estimate_input_visual_rows(columns)
                target_rows = max(base_rows, content_rows)

                # Cap to the space left after the bottom layout has reserved
                # its dynamic rows. A recalled multi-line history entry can be
                # much taller than the terminal; the input window should scroll
                # instead of making the full HSplit impossible to fit.
                desired = max(original_min, target_rows)
                if rows > 0:
                    desired = min(desired, self._get_max_input_window_rows(rows))
                desired = max(1, desired)

                return Dimension(min=1, preferred=desired, max=desired)

            input_window.height = _height

    def _get_max_input_window_rows(self, terminal_rows: int) -> int:
        reserved_rows = self._get_reserved_non_input_rows()
        return max(1, terminal_rows - reserved_rows - _INPUT_HEIGHT_SAFETY_ROWS)

    def _get_reserved_non_input_rows(self) -> int:
        input_rule_rows = 2
        return (
            self._bottom_bar.reserved_layout_rows()
            + input_rule_rows
            + self._get_completion_panel_height()
            + self._get_input_footer_height()
        )

    def _estimate_input_visual_rows(self, columns: int) -> int:
        try:
            text = self._session.default_buffer.text
        except Exception:
            text = ""

        prompt_width = max(get_cwidth(self._prompt_text), get_cwidth("  "))
        available = max(1, columns - prompt_width)
        rows = 0
        for line in text.split("\n"):
            width = get_cwidth(line)
            rows += max(1, (width + available - 1) // available)
        return max(1, rows)

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

    def _mark_queued_edit_active(self, _text: str) -> None:
        self._queued_edit_active = True

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
            main_candidates = config.iter_model_config_candidates(config.main_model)
            initial = main_candidates[0].selector if main_candidates else None
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
        self._bottom_bar.stop()

    @override
    async def iter_inputs(self) -> AsyncIterator[UserInputPayload]:
        # Clear any kitty keyboard-protocol flags leaked into the terminal by
        # a previous program; the REPL expects legacy key encoding. Terminals
        # without kitty protocol silently ignore the sequence.
        with contextlib.suppress(Exception):
            sys.stdout.write(KITTY_KEYBOARD_RESET)
            sys.stdout.flush()

        # Keep one StdoutProxy alive for the entire input session instead of
        # rebuilding it on every prompt_async iteration. The proxy's close()
        # joins its background flush thread, which can block up to
        # ``sleep_between_writes`` seconds waiting for the throttle sleep to
        # finish — that delay was visible as an empty input area between a
        # follow-up submission and the next prompt being rendered.
        with flicker_safe_patch_stdout():
            async for payload in self._iter_inputs_inner():
                yield payload

    async def _iter_inputs_inner(self) -> AsyncIterator[UserInputPayload]:
        while True:
            await self._external_input_resume_event.wait()
            if self._pre_prompt is not None:
                with contextlib.suppress(Exception):
                    self._pre_prompt()

            # Keep ANSI escape sequences intact while prompt_toolkit is active.
            # This allows Rich-rendered panels (e.g. WelcomeEvent) to display with
            # proper styling instead of showing raw escape codes.
            if self._on_prompt_start is not None:
                with contextlib.suppress(Exception):
                    self._on_prompt_start()
            prompt_paused = False
            line = ""
            queued_edit = False
            try:
                self._prompt_active = True
                default_text = self._take_next_prefill_text()
                if default_text is None:
                    line = await self._session.prompt_async(message=self._get_prompt_message)
                else:
                    line = await self._session.prompt_async(message=self._get_prompt_message, default=default_text)
                queued_edit = self._queued_edit_active
            except _PromptPaused:
                prompt_paused = True
            finally:
                self._prompt_active = False
                pause_waiter = self._prompt_pause_waiter
                self._prompt_pause_waiter = None
                if pause_waiter is not None and not pause_waiter.done():
                    pause_waiter.set_result(None)
                # A submission (Enter on non-empty buffer, suggestion acceptance,
                # or anything else) invalidates the pending suggestion. Runtime
                # will push a fresh one after the next task finishes.
                if not prompt_paused:
                    self._prompt_suggestion = None
                    self._queued_edit_active = False
                if self._on_prompt_end is not None:
                    with contextlib.suppress(Exception):
                        self._on_prompt_end()
            if prompt_paused:
                continue
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

            yield UserInputPayload(
                text=line,
                images=images if images else None,
                pasted_files=pasted_files,
                queued_edit=queued_edit,
            )

    # Note: Mouse support is intentionally disabled at the PromptSession
    # level so that terminals retain their native scrollback behavior.
