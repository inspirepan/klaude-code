from __future__ import annotations

import asyncio
import contextlib
import io
import shutil
import time
from collections import deque
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, cast

from rich import box
from rich.console import Console, Group, RenderableType
from rich.padding import Padding
from rich.panel import Panel
from rich.rule import Rule
from rich.segment import Segment
from rich.style import Style, StyleType
from rich.text import Text

from klaude_code.config.formatters import format_number
from klaude_code.const import (
    MARKDOWN_LEFT_MARGIN,
    MARKDOWN_RIGHT_MARGIN,
    STATUS_DEFAULT_TEXT,
)
from klaude_code.log import DebugType, log_debug
from klaude_code.protocol import events, tools
from klaude_code.protocol.models import (
    AtFileImagesUIItem,
    BashUIExtra,
    ImageUIExtra,
    ReadPreviewUIExtra,
    SubAgentState,
    UserImagesUIItem,
)
from klaude_code.tui.commands import (
    AppendAssistant,
    AppendBashCommandOutput,
    AppendThinking,
    DynamicSeparatorText,
    EndAssistantStream,
    EndThinkingStream,
    PrintBlankLine,
    PromptStatusLine,
    RenderAwaySummary,
    RenderBashCommandEnd,
    RenderBashCommandStart,
    RenderCommand,
    RenderCompactionSummary,
    RenderCompactToolResult,
    RenderContextUsage,
    RenderDeveloperMessage,
    RenderError,
    RenderForkCacheHitRate,
    RenderHandoff,
    RenderInterrupt,
    RenderNotice,
    RenderRewind,
    RenderSessionStats,
    RenderSubAgentBatchSummary,
    RenderTaskFileChangeSummary,
    RenderTaskFinish,
    RenderTaskMetadata,
    RenderTaskStart,
    RenderThinkingSummary,
    RenderTimeMarker,
    RenderToolCall,
    RenderToolResult,
    RenderUserMessage,
    RenderWelcome,
    RenderWelcomeContext,
    SeparatorText,
    SpinnerStart,
    SpinnerStatusLine,
    SpinnerStop,
    SpinnerUpdate,
    StartAssistantStream,
    StartThinkingStream,
    StartTitleBlink,
    StopTitleBlink,
    SubAgentSummary,
    TaskClockClear,
    TaskClockStart,
    UpdateTerminalTitlePrefix,
)
from klaude_code.tui.components import away_summary as c_away_summary
from klaude_code.tui.components import command_output as c_command_output
from klaude_code.tui.components import context_usage as c_context_usage
from klaude_code.tui.components import developer as c_developer
from klaude_code.tui.components import errors as c_errors
from klaude_code.tui.components import metadata as c_metadata
from klaude_code.tui.components import sub_agent as c_sub_agent
from klaude_code.tui.components import task_file_changes as c_task_file_changes
from klaude_code.tui.components import thinking as c_thinking
from klaude_code.tui.components import tools as c_tools
from klaude_code.tui.components import user_input as c_user_input
from klaude_code.tui.components import welcome as c_welcome
from klaude_code.tui.components.common import format_more_lines_indicator
from klaude_code.tui.components.rich.markdown import MarkdownStream, NoInsetMarkdown, ThinkingMarkdown
from klaude_code.tui.components.rich.quote import Quote
from klaude_code.tui.components.rich.status import DynamicText, ResponsiveDynamicText, StackedStatusText
from klaude_code.tui.components.rich.theme import ThemeKey, get_theme
from klaude_code.tui.status_runtime import clear_task_start, set_task_start
from klaude_code.tui.terminal.image import print_kitty_image
from klaude_code.tui.terminal.notifier import (
    Notification,
    NotificationType,
    TerminalNotifier,
)
from klaude_code.tui.terminal.title import (
    is_title_blinking,
    start_terminal_title_blink,
    stop_terminal_title_blink,
    update_blink_params,
    update_terminal_title,
)
from klaude_code.tui.transcript_detail import Detail, TranscriptDetail, is_visible

BASH_LIVE_TAIL_MAX_LINES = 5
TASK_NOTIFICATION_DELAY_S = 0.3
_COMPACT_SUB_AGENT_FILE_CHANGE_ACTIONS = {
    tools.EDIT: "Edit",
    tools.WRITE: "Write",
    tools.APPLY_PATCH: "Patch",
}

# A fast-spewing command can deliver hundreds of output deltas per second;
# rendering the tail through Rich for each one wastes event-loop time. Cap
# tail repaints and flush trailing content once the interval elapses.
BASH_LIVE_TAIL_MIN_INTERVAL_S = 1 / 30

# Spinner updates are emitted per streamed LLM delta; rebuilding the Rich
# status snapshot for each one costs far more than the visible change (the
# status text only moves at sub-second granularity). Coalesce rebuilds to a
# fixed cadence and flush the trailing state once the interval elapses.
SPINNER_UPDATE_MIN_INTERVAL_S = 1 / 10

# Dedup key for spinner updates. `reset_bottom_height` only participates in
# the key; it carries no rendering state of its own.
_SpinnerUpdateKey = tuple[object, object, object, object, object]


def _text_fingerprint(text: Text) -> tuple[str, str, tuple[tuple[int, int, str], ...]]:
    """Content fingerprint of a Text: plain text, root style, and styled spans."""
    spans = tuple((span.start, span.end, str(span.style)) for span in text.spans)
    return (text.plain, str(text.style) if text.style else "", spans)


class _TerminalCaptureBuffer(io.StringIO):
    """In-memory sink that reports as a terminal so ANSI styling is kept."""

    def isatty(self) -> bool:
        return True


@dataclass
class _ActiveStream:
    buffer: str
    mdstream: MarkdownStream

    def append(self, content: str) -> None:
        self.buffer += content


class _StreamState:
    def __init__(self) -> None:
        self._active: _ActiveStream | None = None

    @property
    def is_active(self) -> bool:
        return self._active is not None

    @property
    def buffer(self) -> str:
        return self._active.buffer if self._active else ""

    def start(self, mdstream: MarkdownStream) -> None:
        self._active = _ActiveStream(buffer="", mdstream=mdstream)

    def append(self, content: str) -> None:
        if self._active is None:
            return
        self._active.append(content)

    def render(self, *, transform: Callable[[str], str] | None = None, final: bool = False) -> bool:
        if self._active is None:
            return False
        text = self._active.buffer
        if transform is not None:
            text = transform(text)
        self._active.mdstream.update(text, final=final)
        if final:
            self._active = None
        return True

    def finalize(self, *, transform: Callable[[str], str] | None = None) -> bool:
        return self.render(transform=transform, final=True)


@dataclass
class _SessionStatus:
    color: Style | None = None
    color_index: int | None = None
    sub_agent_state: SubAgentState | None = None


class TUICommandRenderer:
    """Execute RenderCommand sequences and render them to the terminal.

    This is the only component that performs actual terminal rendering.
    """

    def __init__(
        self,
        theme: str | None = None,
        notifier: TerminalNotifier | None = None,
        status_sink: Callable[[tuple[PromptStatusLine, ...], str | None, bool], None] | None = None,
        stream_sink: Callable[[tuple[str, ...], bool], None] | None = None,
        detail: TranscriptDetail | None = None,
    ) -> None:
        self.themes = get_theme(theme)
        self.console: Console = Console(theme=self.themes.app_theme)
        self.console.push_theme(self.themes.markdown_theme)

        self._stream_renderable: RenderableType | None = None
        self._spinner_visible: bool = False
        self._progress_ui_suspended: bool = False
        self._spinner_last_update_key: _SpinnerUpdateKey | None = None
        self._spinner_pending_update: SpinnerUpdate | None = None
        self._spinner_flush_handle: asyncio.TimerHandle | None = None
        self._spinner_last_apply_at: float = 0.0
        self._status_metadata_text: RenderableType | None = None
        self._status_separator_text: SeparatorText | None = None

        self._status_text: StackedStatusText = StackedStatusText(
            None,
            (Text(STATUS_DEFAULT_TEXT, style=ThemeKey.STATUS_TEXT),),
            show_hint=False,
            shimmer=False,
        )
        self._status_line_specs: tuple[SpinnerStatusLine, ...] = ()
        self._notifier = notifier
        self._scrollback_boundary_printed = False
        self._status_gap_in_scrollback = False
        self._status_sink = status_sink
        self._stream_sink = stream_sink
        self._assistant_stream = _StreamState()
        self._thinking_stream = _StreamState()

        # Replay mode reuses the same event/state machine but does not need streaming UI.
        # When enabled, we avoid bottom Live rendering and defer markdown rendering until
        # the corresponding stream End event.
        self._replay_mode: bool = False

        self._bash_stream_active: bool = False
        self._bash_live_tail_lines: deque[str] = deque(maxlen=BASH_LIVE_TAIL_MAX_LINES)
        self._bash_live_partial_line: str = ""
        self._bash_live_hidden_lines: int = 0
        self._bash_live_last_render_at: float = 0.0
        self._bash_live_flush_handle: asyncio.TimerHandle | None = None

        self._sessions: dict[str, _SessionStatus] = {}
        self._current_sub_agent_color: Style | None = None
        self._sub_agent_color_index = 0
        self._sub_agent_batch_color_starts: dict[str, int] = {}
        self._continuous_block_session_id: str | None = None
        self._detail = detail if detail is not None else TranscriptDetail()

    def set_transcript_detail(self, detail: Detail) -> None:
        self._detail.set(detail)

    @property
    def _compact(self) -> bool:
        return self._detail.is_compact

    def _visible(self, event: events.Event) -> bool:
        """Whether this event prints at the current detail level.

        The policy lives in `transcript_detail`; each display method only asks,
        after any bookkeeping it owns (e.g. session registration) has run.
        """
        return is_visible(
            event,
            detail=self._detail.current,
            is_sub_agent=self.is_sub_agent_session(event.session_id),
        )

    def set_replay_mode(self, enabled: bool) -> None:
        """Enable or disable replay rendering mode.

        Replay mode is optimized for speed and stability:
        - Avoid Rich Live / bottom status rendering.
        - Defer markdown stream rendering until End events.
        """

        self._replay_mode = enabled

    def reset_replay_state(self) -> None:
        self._sessions = {}
        self._sub_agent_color_index = 0
        self._sub_agent_batch_color_starts = {}
        self._current_sub_agent_color = None
        self._assistant_stream = _StreamState()
        self._thinking_stream = _StreamState()
        self._clear_open_blocks()

    @contextmanager
    def bulk_render_capture(self) -> Iterator[io.StringIO]:
        """Render into memory instead of the terminal.

        Console output (including kitty image escapes, which also write to
        ``console.file``) accumulates in the returned buffer in order. The
        console size is pinned first: with an in-memory file Rich would fall
        back to environment-based size detection mid-capture. The caller
        flushes the buffer in a single scrollback write so the whole payload
        paints at once (see ``write_scrollback_bulk``).
        """

        console = self.console
        buffer = _TerminalCaptureBuffer()
        size = console.size
        old_width, old_height = console._width, console._height  # pyright: ignore[reportPrivateUsage]
        old_file = console._file  # pyright: ignore[reportPrivateUsage]
        console.size = size
        console.file = buffer
        try:
            yield buffer
        finally:
            console._file = old_file  # pyright: ignore[reportPrivateUsage]
            console._width = old_width  # pyright: ignore[reportPrivateUsage]
            console._height = old_height  # pyright: ignore[reportPrivateUsage]

    # ---------------------------------------------------------------------
    # Session helpers
    # ---------------------------------------------------------------------

    def register_session(self, session_id: str, sub_agent_state: SubAgentState | None = None) -> None:
        st = _SessionStatus(sub_agent_state=sub_agent_state)
        if sub_agent_state is not None:
            batch_id = sub_agent_state.parent_tool_batch_id
            batch_index = sub_agent_state.parent_tool_batch_index
            batch_size = sub_agent_state.parent_tool_batch_size
            if self._compact and batch_id is not None and batch_index is not None and self.themes.sub_agent_styles:
                palette_size = len(self.themes.sub_agent_styles)
                batch_color_start = self._sub_agent_batch_color_starts.get(batch_id)
                if batch_color_start is None:
                    batch_color_start = self._sub_agent_color_index
                    self._sub_agent_batch_color_starts[batch_id] = batch_color_start
                    reserved_colors = max(batch_size or 0, batch_index + 1)
                    self._sub_agent_color_index = (batch_color_start + reserved_colors) % palette_size
                color_index = (batch_color_start + batch_index + 1) % palette_size
                color = self.themes.sub_agent_styles[color_index]
            else:
                color, color_index = self._pick_sub_agent_color()
            st.color = color
            st.color_index = color_index
        self._sessions[session_id] = st

    def is_sub_agent_session(self, session_id: str) -> bool:
        return session_id in self._sessions and self._sessions[session_id].sub_agent_state is not None

    def _advance_sub_agent_color_index(self) -> None:
        palette_size = len(self.themes.sub_agent_styles)
        if palette_size == 0:
            self._sub_agent_color_index = 0
            return
        self._sub_agent_color_index = (self._sub_agent_color_index + 1) % palette_size

    def _pick_sub_agent_color(self) -> tuple[Style, int]:
        self._advance_sub_agent_color_index()
        palette = self.themes.sub_agent_styles
        if not palette:
            return Style(), 0
        return palette[self._sub_agent_color_index], self._sub_agent_color_index

    def _get_session_sub_agent_color(self, session_id: str) -> Style:
        st = self._sessions.get(session_id)
        if st and st.color:
            return st.color
        return Style()

    @contextmanager
    def session_print_context(self, session_id: str) -> Iterator[None]:
        """Temporarily switch to sub-agent quote style."""

        st = self._sessions.get(session_id)
        if st is not None and st.color:
            self._current_sub_agent_color = st.color
        try:
            yield
        finally:
            self._current_sub_agent_color = None

    # ---------------------------------------------------------------------
    # Low-level printing & bottom status
    # ---------------------------------------------------------------------

    def print(self, *objects: Any, style: StyleType | None = None, end: str = "\n") -> None:
        if self._current_sub_agent_color:
            if objects:
                self._set_scrollback_boundary(False)
                content = objects[0] if len(objects) == 1 else objects
                self.console.print(
                    Quote(content, style=Style(color=self._current_sub_agent_color.color), prefix="▌ "),
                    overflow="ellipsis",
                )
            elif not self._scrollback_boundary_printed:
                self._set_scrollback_boundary(True)
                self.console.print(
                    Quote(Text(""), style=Style(color=self._current_sub_agent_color.color), prefix="▌ "),
                    overflow="ellipsis",
                )
            return
        if not objects and self._scrollback_boundary_printed:
            return
        self._set_scrollback_boundary(not objects)
        self.console.print(*objects, style=style, end=end, overflow="ellipsis")

    def _set_scrollback_boundary(self, printed: bool, *, status_gap: bool | None = None) -> None:
        resolved_status_gap = printed if status_gap is None else status_gap
        if self._scrollback_boundary_printed == printed and self._status_gap_in_scrollback == resolved_status_gap:
            return
        self._scrollback_boundary_printed = printed
        self._status_gap_in_scrollback = resolved_status_gap
        if self._progress_ui_suspended and self._spinner_visible:
            self._emit_prompt_status()

    def _clear_open_blocks(self) -> None:
        self._continuous_block_session_id = None

    def _open_continuous_block(self, session_id: str) -> None:
        self._continuous_block_session_id = session_id

    def _print_blank_line(self, session_id: str | None = None) -> None:
        if session_id is not None and self.is_sub_agent_session(session_id):
            with self.session_print_context(session_id):
                self.print()
        else:
            self.print()

    def _flush_open_blocks(self, *, scoped: bool = True) -> None:
        if self._continuous_block_session_id is None:
            return
        session_id = self._continuous_block_session_id
        self._print_blank_line(session_id if scoped else None)
        self._clear_open_blocks()

    def flush_open_blocks(self, *, scoped: bool = True) -> None:
        self._flush_open_blocks(scoped=scoped)

    def _flush_open_blocks_before(self, cmd: RenderCommand) -> None:
        if self._continuous_block_session_id is None:
            return

        match cmd:
            case PrintBlankLine():
                self._clear_open_blocks()
                return
            case SpinnerStart() | SpinnerStop() | SpinnerUpdate() | TaskClockStart() | TaskClockClear():
                return
            case UpdateTerminalTitlePrefix() | StartTitleBlink() | StopTitleBlink():
                return
            case (
                RenderToolCall()
                | RenderToolResult()
                | RenderCompactToolResult()
                | RenderBashCommandStart()
                | AppendBashCommandOutput()
                | RenderBashCommandEnd()
            ):
                return
            case RenderDeveloperMessage():
                return
            case _:
                self._flush_open_blocks()

    def spinner_start(self) -> None:
        self._spinner_visible = True
        if not self._flush_pending_spinner_update():
            self._emit_prompt_status()

    def spinner_stop(self) -> None:
        self._flush_pending_spinner_update()
        self._spinner_visible = False
        self._status_separator_text = None
        self._emit_prompt_status(self._prompt_metadata_lines(), None)

    def spinner_update(
        self,
        metadata_text: RenderableType | None = None,
        status_lines: tuple[SpinnerStatusLine, ...] = (),
        separator_text: SeparatorText | None = None,
        reset_bottom_height: bool = False,
    ) -> None:
        update = SpinnerUpdate(
            right_text=metadata_text,
            status_lines=status_lines,
            separator_text=separator_text,
            reset_bottom_height=reset_bottom_height,
        )
        # Inside the throttle window the payload is stashed as-is; the
        # (comparatively expensive) content key is only materialized when an
        # update is actually applied.
        if time.monotonic() - self._spinner_last_apply_at < SPINNER_UPDATE_MIN_INTERVAL_S:
            if self._spinner_pending_update is not None and self._spinner_pending_update.reset_bottom_height:
                update = replace(update, reset_bottom_height=True)
            self._spinner_pending_update = update
            self._schedule_spinner_flush()
            return
        self._cancel_spinner_flush()
        self._spinner_pending_update = None
        self._apply_spinner_update(update)

    def _spinner_update_key(self, update: SpinnerUpdate) -> _SpinnerUpdateKey:
        return (
            self._spinner_right_text_key(update.right_text),
            tuple(
                (
                    line.session_id,
                    line.sub_agent_continuation,
                    line.sub_agent_animated,
                    self._spinner_text_key(line.text),
                )
                for line in update.status_lines
            ),
            update.separator_text,
            update.reset_bottom_height,
            self._status_gap_in_scrollback,
        )

    def _apply_spinner_update(self, update: SpinnerUpdate) -> bool:
        """Apply a spinner update unless its rendered content is unchanged.

        Returns True when a new status snapshot was emitted.
        """
        new_key = self._spinner_update_key(update)
        if new_key == self._spinner_last_update_key:
            return False
        self._spinner_last_update_key = new_key
        self._spinner_last_apply_at = time.monotonic()
        self._status_metadata_text = update.right_text
        self._status_separator_text = update.separator_text
        self._status_line_specs = update.status_lines

        rendered_status_lines = tuple(self._render_status_line(line) for line in update.status_lines)

        self._status_text = StackedStatusText(
            metadata_text=update.right_text,
            status_lines=rendered_status_lines,
            show_hint=False,
            shimmer=False,
        )
        self._emit_prompt_status(reset_bottom_height=update.reset_bottom_height)
        return True

    def _schedule_spinner_flush(self) -> None:
        if self._spinner_flush_handle is not None:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # No running loop (synchronous callers, e.g. tests): apply now so
            # behavior matches the un-throttled contract.
            self._flush_pending_spinner_update()
            return
        due = self._spinner_last_apply_at + SPINNER_UPDATE_MIN_INTERVAL_S
        self._spinner_flush_handle = loop.call_later(max(0.0, due - time.monotonic()), self._flush_spinner_update)

    def _flush_spinner_update(self) -> None:
        self._spinner_flush_handle = None
        self._flush_pending_spinner_update()

    def _flush_pending_spinner_update(self) -> bool:
        """Apply any pending update now, cancelling a scheduled flush.

        Returns True when a new status snapshot was emitted.
        """
        self._cancel_spinner_flush()
        pending = self._spinner_pending_update
        if pending is None:
            return False
        self._spinner_pending_update = None
        return self._apply_spinner_update(pending)

    def _cancel_spinner_flush(self) -> None:
        handle = self._spinner_flush_handle
        if handle is None:
            return
        self._spinner_flush_handle = None
        with contextlib.suppress(Exception):
            handle.cancel()

    def set_progress_ui_suspended(self, suspended: bool) -> None:
        self._progress_ui_suspended = suspended
        if not suspended:
            self._cancel_spinner_flush()
            self._spinner_pending_update = None
            self._emit_prompt_status((), None)
            self._emit_prompt_stream((), end_of_stream=True)
            return
        self._flush_pending_spinner_update()
        self._emit_prompt_status()

    def _emit_prompt_status(
        self,
        lines: tuple[PromptStatusLine, ...] | None = None,
        separator_text: SeparatorText | None = None,
        reset_bottom_height: bool = False,
    ) -> None:
        if self._status_sink is None:
            return
        if lines is None:
            lines = self._prompt_status_lines()
            separator_text = self._status_separator_text
        resolved_separator_text = self._resolve_separator_text(separator_text)
        self._status_sink(lines, resolved_separator_text, reset_bottom_height)

    @staticmethod
    def _resolve_separator_text(separator_text: SeparatorText | None) -> str | None:
        if separator_text is None:
            return None
        if isinstance(separator_text, DynamicSeparatorText):
            return separator_text.render()
        return separator_text

    def refresh_prompt_status(self) -> None:
        if self._progress_ui_suspended and not self._flush_pending_spinner_update():
            self._emit_prompt_status()

    def _prompt_status_lines(self) -> tuple[PromptStatusLine, ...]:
        if not (self._progress_ui_suspended and self._spinner_visible):
            return ()
        rendered = self.console.render_lines(self._status_text, self.console.options, pad=False)
        lines = tuple("".join(segment.text for segment in line if not segment.control).rstrip() for line in rendered)
        nonempty_lines = [line for line in lines if line]
        if not nonempty_lines:
            return ()
        result: list[PromptStatusLine] = []
        status_index = 0
        for line, rendered_line in zip(lines, rendered, strict=True):
            if not line:
                continue
            fragments = self._prompt_status_fragments(rendered_line)
            inline_spinner_style: str | None = None
            show_spinner = True
            spec = self._status_line_specs[status_index] if status_index < len(self._status_line_specs) else None
            if spec is not None:
                status_index += 1
                if spec.sub_agent_continuation:
                    show_spinner = False
                elif spec.session_id is not None and self.is_sub_agent_session(spec.session_id):
                    show_spinner = False
                    if spec.sub_agent_animated and fragments:
                        inline_spinner_style = fragments[0][0]
                        fragments = self._strip_prompt_fragment_prefix(fragments, 4)
            result.append(
                PromptStatusLine(
                    line,
                    "status",
                    fragments,
                    show_spinner,
                    inline_spinner_style,
                    self._status_gap_in_scrollback,
                )
            )
        if self._status_metadata_text is not None:
            result[-1] = PromptStatusLine(
                result[-1].text,
                "metadata",
                result[-1].fragments,
                result[-1].show_spinner,
                result[-1].inline_spinner_style,
                result[-1].suppress_top_spacer,
            )
        return tuple(result)

    @staticmethod
    def _prompt_status_fragments(segments: list[Segment]) -> tuple[tuple[str, str], ...]:
        fragments: list[tuple[str, str]] = []
        for segment in segments:
            if segment.control or not segment.text:
                continue
            style = segment.style
            attrs: list[str] = []
            if style is not None:
                if style.color is not None:
                    triplet = style.color.get_truecolor()
                    attrs.append(f"fg:#{triplet.red:02x}{triplet.green:02x}{triplet.blue:02x}")
                if style.bgcolor is not None:
                    triplet = style.bgcolor.get_truecolor()
                    attrs.append(f"bg:#{triplet.red:02x}{triplet.green:02x}{triplet.blue:02x}")
                for enabled, name in (
                    (style.bold, "bold"),
                    (style.italic, "italic"),
                    (style.underline, "underline"),
                    (style.reverse, "reverse"),
                ):
                    if enabled:
                        attrs.append(name)
            fragments.append((" ".join(attrs) or "class:meta", segment.text))
        while fragments and fragments[-1][1].endswith(" "):
            style, text = fragments[-1]
            stripped = text.rstrip()
            if stripped:
                fragments[-1] = (style, stripped)
                break
            fragments.pop()
        return tuple(fragments)

    @staticmethod
    def _strip_prompt_fragment_prefix(
        fragments: tuple[tuple[str, str], ...], prefix_length: int
    ) -> tuple[tuple[str, str], ...]:
        remaining = prefix_length
        stripped: list[tuple[str, str]] = []
        for style, text in fragments:
            if remaining >= len(text):
                remaining -= len(text)
                continue
            if remaining:
                text = text[remaining:]
                remaining = 0
            if text:
                stripped.append((style, text))
        return tuple(stripped)

    def _prompt_metadata_lines(self) -> tuple[PromptStatusLine, ...]:
        if self._status_metadata_text is None:
            return ()
        rendered = self.console.render_lines(self._status_metadata_text, self.console.options, pad=False)
        lines = tuple("".join(segment.text for segment in line if not segment.control).rstrip() for line in rendered)
        return tuple(
            PromptStatusLine(
                line,
                "metadata",
                suppress_top_spacer=self._status_gap_in_scrollback,
            )
            for line in lines
            if line
        )

    def _emit_prompt_stream(
        self,
        lines: tuple[str, ...] | None = None,
        *,
        end_of_stream: bool = False,
    ) -> None:
        if self._stream_sink is None:
            return
        self._stream_sink(lines or (), end_of_stream)

    def _prompt_stream_lines(self, renderable: RenderableType) -> tuple[str, ...]:
        rendered = self.console.render_lines(renderable, self.console.options, pad=False)
        lines = tuple("".join(segment.text for segment in line if not segment.control).rstrip() for line in rendered)
        return tuple(line for line in lines if line)

    def _render_status_line(self, line: SpinnerStatusLine) -> RenderableType:
        text = line.text
        session_id = line.session_id
        if session_id is None or not self.is_sub_agent_session(session_id):
            return text

        color = self._get_session_sub_agent_color(session_id)
        fg_only = Style(color=color.color)

        if not self._compact:

            def _render_expanded() -> Text:
                if isinstance(text, DynamicText):
                    content = text.snapshot()
                elif isinstance(text, Text):
                    content = text.copy()
                else:
                    content = Text(str(text))
                if content.plain:
                    content.stylize(fg_only, 0, len(content))
                return content

            return DynamicText(_render_expanded) if isinstance(text, DynamicText) else _render_expanded()

        def _render() -> Text:
            if isinstance(text, DynamicText):
                content = text.snapshot()
            elif isinstance(text, Text):
                content = text.copy()
            else:
                content = Text(str(text))
            if line.sub_agent_continuation:
                for span in tuple(content.spans):
                    if span.style == ThemeKey.TOOL_NAME:
                        content.stylize(Style(bold=False), span.start, span.end)
                marker = (
                    c_sub_agent.COMPACT_CONTINUATION_PREFIX
                    if line.continuation_leading
                    else c_sub_agent.COMPACT_CONTINUATION_INDENT
                )
                prefix_text = f"      {marker}"
            elif line.sub_agent_animated:
                prefix_text = "··· "
            else:
                prefix_text = " ●  "
            prefix = Text(prefix_text, style=fg_only)
            rendered = Text.assemble(prefix, content)
            if not line.sub_agent_continuation:
                boundaries = [
                    index for marker in (" · ", " ✓", " ✗", " cancelled") if (index := content.plain.find(marker)) >= 0
                ]
                identity_end = min(boundaries, default=len(content))
                rendered.stylize(fg_only, 0, len(prefix) + identity_end)
            return rendered

        return DynamicText(_render) if isinstance(text, DynamicText) else _render()

    @staticmethod
    def _spinner_text_key(text: RenderableType) -> object:
        if isinstance(text, DynamicText):
            return ("DynamicText", *_text_fingerprint(text.snapshot()))
        if isinstance(text, Text):
            return ("Text", *_text_fingerprint(text))
        if isinstance(text, str):
            return ("str", text)
        return ("other", id(text))

    @staticmethod
    def _spinner_right_text_key(text: RenderableType | None) -> object:
        if text is None:
            return ("none",)
        if isinstance(text, ResponsiveDynamicText):
            # The narrow variant derives from the same state, so fingerprinting
            # the full render is enough to detect content changes.
            return ("ResponsiveDynamicText", *_text_fingerprint(text.render(narrow=False)))
        if isinstance(text, Text):
            return ("Text", *_text_fingerprint(text))
        if isinstance(text, str):
            return ("str", text)
        if isinstance(text, DynamicText):
            return ("DynamicText", *_text_fingerprint(text.snapshot()))
        # Fall back to a unique key so we never skip updates for unknown renderables.
        return ("other", object())

    def set_stream_renderable(self, renderable: RenderableType | None) -> None:
        if renderable is None:
            self._stream_renderable = None
            self._emit_prompt_stream((), end_of_stream=True)
            return

        self._stream_renderable = renderable
        self._emit_prompt_stream(self._prompt_stream_lines(renderable))

    # ---------------------------------------------------------------------
    # Stream helpers (MarkdownStream)
    # ---------------------------------------------------------------------

    def _new_thinking_mdstream(self) -> MarkdownStream:
        return MarkdownStream(
            mdargs={
                "code_theme": self.themes.code_theme,
                "style": ThemeKey.THINKING,
            },
            theme=self.themes.thinking_markdown_theme,
            console=self.console,
            live_sink=None,
            mark="∵",
            mark_style=ThemeKey.THINKING,
            left_margin=MARKDOWN_LEFT_MARGIN,
            right_margin=MARKDOWN_RIGHT_MARGIN,
            markdown_class=ThinkingMarkdown,
            scrollback_write_sink=self._mark_scrollback_content,
        )

    def _new_assistant_mdstream(self) -> MarkdownStream:
        live_sink = None if self._replay_mode else self.set_stream_renderable
        return MarkdownStream(
            mdargs={"code_theme": self.themes.code_theme},
            theme=self.themes.markdown_theme,
            console=self.console,
            live_sink=live_sink,
            mark="●",
            left_margin=MARKDOWN_LEFT_MARGIN,
            right_margin=MARKDOWN_RIGHT_MARGIN,
            image_callback=self.display_image,
            scrollback_write_sink=self._mark_scrollback_content,
        )

    def _mark_scrollback_content(self) -> None:
        self._set_scrollback_boundary(False)

    def _flush_thinking(self) -> None:
        self._thinking_stream.render(transform=c_thinking.normalize_thinking_content)

    def _flush_assistant(self) -> None:
        self._assistant_stream.render()

    # ---------------------------------------------------------------------
    # Event-specific rendering helpers
    # ---------------------------------------------------------------------

    def display_tool_call(self, e: events.ToolCallEvent) -> bool:
        if not self._visible(e):
            return False
        if c_tools.is_sub_agent_tool(e.tool_name):
            return False
        renderable = c_tools.render_tool_call(e)
        if renderable is not None:
            self.print(renderable)
            return True
        return False

    def display_tool_call_result(self, e: events.ToolResultEvent, *, is_sub_agent: bool = False) -> bool:
        if self._compact and is_sub_agent:
            action = _COMPACT_SUB_AGENT_FILE_CHANGE_ACTIONS.get(e.tool_name)
            session = self._sessions.get(e.session_id)
            if action is None or session is None or session.sub_agent_state is None:
                return False
            change = c_tools.render_compact_file_change(e, code_theme=self.themes.code_theme)
            if change is None:
                return False
            self.print(
                c_sub_agent.render_compact_file_change(
                    sub_agent_state=session.sub_agent_state,
                    action=c_tools.render_compact_file_change_action(e, action),
                    change=change,
                    color=self._get_session_sub_agent_color(e.session_id),
                )
            )
            return True
        if c_tools.is_sub_agent_tool(e.tool_name):
            return False

        if (
            self._compact
            and not is_sub_agent
            and e.tool_name == tools.READ
            and isinstance(e.ui_extra, ReadPreviewUIExtra)
        ):
            return False

        # Fetched page content is bulky and the tool call line already shows the
        # URL, so drop the body in compact transcript mode (same as Read).
        if self._compact and not is_sub_agent and e.tool_name == tools.WEB_FETCH and not e.is_error:
            return False

        if is_sub_agent and e.is_error:
            style = ThemeKey.INTERRUPT if e.status == "aborted" else ThemeKey.ERROR
            self.print(c_errors.render_tool_error(e.result, style=style, detail=self._detail.current))
            return True

        if not is_sub_agent and isinstance(e.ui_extra, ImageUIExtra):
            self.display_image(e.ui_extra.file_path)

        renderable = c_tools.render_tool_result(e, code_theme=self.themes.code_theme, detail=self._detail.current)
        if renderable is not None:
            self.print(renderable)
            return True
        return False

    def display_compact_tool_result(self, event: events.ToolResultEvent, arguments: str) -> None:
        exit_code = event.ui_extra.exit_code if isinstance(event.ui_extra, BashUIExtra) else None
        self.print(
            c_tools.render_compact_tool_result(
                event.tool_name,
                arguments,
                event.result,
                status=event.status,
                exit_code=exit_code,
            )
        )

    def display_developer_message(self, e: events.DeveloperMessageEvent) -> bool:
        if not self._visible(e):
            return False
        if not c_developer.need_render_developer_message(e):
            return False
        with self.session_print_context(e.session_id):
            self.print(c_developer.render_developer_message(e))

        # Display images from @ file references and user attachments
        if e.item.ui_extra:
            for ui_item in e.item.ui_extra.items:
                if isinstance(ui_item, (AtFileImagesUIItem, UserImagesUIItem)):
                    for image_path in ui_item.paths:
                        self.display_image(image_path)
        return True

    def display_notice(self, e: events.NoticeEvent) -> None:
        if not self._visible(e):
            return
        with self.session_print_context(e.session_id):
            self.print(c_command_output.render_notice(e))
            self.print()

    def display_away_summary(self, e: events.AwaySummaryEvent) -> None:
        if not self._visible(e):
            return
        with self.session_print_context(e.session_id):
            self.print(c_away_summary.render_away_summary(e))
            self.print()

    def display_session_stats(self, e: events.SessionStatsEvent) -> None:
        if not self._visible(e):
            return
        with self.session_print_context(e.session_id):
            self.print(c_command_output.render_session_stats(e))
            self.print()

    def display_context_usage(self, e: events.ContextUsageEvent) -> None:
        if not self._visible(e):
            return
        with self.session_print_context(e.session_id):
            self.print(c_context_usage.render_context_usage(e))
            self.print()

    def display_bash_command_start(self, e: events.BashCommandStartEvent) -> None:
        # The user input line already shows `!cmd`; bash output is streamed as it arrives.
        # We keep minimal rendering here to avoid adding noise.
        del e
        self._cancel_bash_live_flush()
        self._bash_stream_active = True
        self._bash_live_tail_lines.clear()
        self._bash_live_partial_line = ""
        self._bash_live_hidden_lines = 0

    def _append_bash_live_tail(self, content: str) -> None:
        merged = self._bash_live_partial_line + content
        if not merged:
            return

        parts = merged.splitlines(keepends=True)
        if parts and not parts[-1].endswith(("\n", "\r")):
            self._bash_live_partial_line = parts[-1]
            complete = parts[:-1]
        else:
            self._bash_live_partial_line = ""
            complete = parts

        for part in complete:
            if len(self._bash_live_tail_lines) == self._bash_live_tail_lines.maxlen:
                self._bash_live_hidden_lines += 1
            self._bash_live_tail_lines.append(part.rstrip("\r\n"))

    def _schedule_bash_live_tail_render(self) -> None:
        if self._bash_live_flush_handle is not None:
            return
        now = time.monotonic()
        due = self._bash_live_last_render_at + BASH_LIVE_TAIL_MIN_INTERVAL_S
        if now >= due:
            self._render_bash_live_tail()
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            self._render_bash_live_tail()
            return
        self._bash_live_flush_handle = loop.call_later(due - now, self._flush_bash_live_tail)

    def _flush_bash_live_tail(self) -> None:
        self._bash_live_flush_handle = None
        if self._bash_stream_active:
            self._render_bash_live_tail()

    def _cancel_bash_live_flush(self) -> None:
        handle = self._bash_live_flush_handle
        if handle is None:
            return
        self._bash_live_flush_handle = None
        with contextlib.suppress(Exception):
            handle.cancel()

    def _render_bash_live_tail(self) -> None:
        self._bash_live_last_render_at = time.monotonic()
        lines = list(self._bash_live_tail_lines)
        if self._bash_live_partial_line:
            lines.append(self._bash_live_partial_line)

        rendered = Text(style=ThemeKey.TOOL_RESULT)
        if self._bash_live_hidden_lines > 0:
            rendered.append(
                format_more_lines_indicator(self._bash_live_hidden_lines),
                style=ThemeKey.TOOL_RESULT_TRUNCATED,
            )
            if lines:
                rendered.append("\n")

        rendered.append("\n".join(lines))
        self.set_stream_renderable(c_tools.indent_bash_output(rendered))

    def display_bash_command_delta(self, e: events.BashCommandOutputDeltaEvent) -> None:
        if not self._bash_stream_active:
            self._bash_stream_active = True
            self._bash_live_tail_lines.clear()
            self._bash_live_partial_line = ""
            self._bash_live_hidden_lines = 0

        content = e.content
        if content == "":
            return

        self._append_bash_live_tail(content)
        self._schedule_bash_live_tail_render()

    def display_bash_command_end(self, e: events.BashCommandEndEvent) -> None:
        del e
        self._cancel_bash_live_flush()
        if self._bash_stream_active:
            self.set_stream_renderable(None)
        self._bash_stream_active = False
        self._bash_live_tail_lines.clear()
        self._bash_live_partial_line = ""
        self._bash_live_hidden_lines = 0

    def display_welcome(self, event: events.WelcomeEvent) -> None:
        self.print(c_welcome.render_welcome(event))

    def display_welcome_context(self, event: events.WelcomeContextEvent) -> None:
        context = c_welcome.render_welcome_context(event)
        if context is not None:
            self.print(context)

    def display_user_message(self, event: events.UserMessageEvent) -> None:
        self.print(c_user_input.render_user_input(event.content))
        self.print()
        self._set_scrollback_boundary(True, status_gap=False)

    def display_time_marker(self, label: str) -> None:
        self.print(Text(f" ⏱ {label} ", style=ThemeKey.TIME_MARKER))
        self.print()

    def display_task_start(self, event: events.TaskStartEvent) -> None:
        # Registration owns the session's color slot and must happen at every
        # detail level -- `_visible` also depends on it.
        self.register_session(event.session_id, event.sub_agent_state)
        if event.sub_agent_state is None or not self._visible(event):
            return
        with self.session_print_context(event.session_id):
            self.print(
                c_sub_agent.render_sub_agent_call(
                    event.sub_agent_state,
                    self._get_session_sub_agent_color(event.session_id),
                    code_theme=self.themes.code_theme,
                    effective_model=event.model_id,
                )
            )
        self._print_blank_line(event.session_id)

    def display_step_start(self, event: events.StepStartEvent) -> None:
        del event

    def display_image(self, file_path: str, caption: str | None = None) -> None:
        self._set_scrollback_boundary(False)
        if caption:
            caption_style = self.console.get_style("markdown.image.placeholder", default="dim")
            caption_text = caption_style.render(
                f"\n↓ {caption}",
                color_system=cast(Any, self.console.color_system),
            )
            print(caption_text, file=self.console.file, flush=True)
        path = Path(file_path)
        if not path.exists():
            self.print(
                c_tools.AdaptiveIndent(
                    Text(f"Image not found: {path}", style=ThemeKey.TOOL_RESULT, overflow="ellipsis", no_wrap=True),
                    c_tools.TOOL_SUBJECT_INDENT,
                )
            )
            return
        print_kitty_image(file_path, file=self.console.file)

    def display_task_metadata(self, event: events.TaskMetadataEvent) -> None:
        if not self._visible(event):
            return
        renderable = c_metadata.render_task_metadata(event, detail=self._detail.current)
        if renderable is None:
            return
        self.print(renderable)
        self.print()

    def display_task_file_change_summary(self, event: events.TaskFileChangeSummaryEvent) -> None:
        if not self._visible(event):
            return
        self.print(c_task_file_changes.render_task_file_change_summary(event))
        self.print()

    def display_task_finish(self, event: events.TaskFinishEvent) -> None:
        if not self._visible(event):
            return
        sub_agent_state = self._sessions[event.session_id].sub_agent_state
        if sub_agent_state is None:
            return
        with self.session_print_context(event.session_id):
            self.print(
                c_sub_agent.render_sub_agent_result(
                    event.task_result,
                    description=sub_agent_state.sub_agent_desc,
                    sub_agent_color=self._current_sub_agent_color,
                )
            )

    def display_sub_agent_batch_summary(self, summaries: tuple[SubAgentSummary, ...]) -> None:
        rendered: list[RenderableType] = []
        for summary in summaries:
            session_id = summary.session_id
            color = self._get_session_sub_agent_color(session_id)
            content = c_sub_agent.render_compact_sub_agent_summary(
                title=summary.title,
                description=summary.description,
                status=summary.status,
                model_id=summary.model_id,
                duration_s=summary.duration_s,
                tool_count=summary.tool_count,
                token_count=summary.token_count,
                result_summary=summary.result_summary,
                color=color,
            )
            rendered.append(
                Quote(
                    content,
                    style=Style(color=color.color),
                    prefix="▌ ",
                )
            )
        if summaries:
            self.print(Group(*rendered))
            self.print()

    def display_interrupt(self) -> None:
        self.print(c_user_input.render_interrupt())
        self.print()

    def display_error(self, event: events.ErrorEvent) -> None:
        if not self._visible(event):
            return
        message = event.compact_message if self._compact and event.compact_message else event.error_message
        if event.session_id:
            with self.session_print_context(event.session_id):
                self.print(c_errors.render_error(Text(message), can_retry=event.can_retry))
        else:
            self.print(c_errors.render_error(Text(message), can_retry=event.can_retry))
        self.print()

    @staticmethod
    def _strip_summary_tags(text: str) -> str:
        """Remove XML-ish wrapper tags from compaction/handoff summaries."""
        return (
            text.replace("<summary>", "")
            .replace("</summary>", "")
            .replace("<read_files>", "")
            .replace("</read_files>", "")
            .replace("<modified-files>", "")
            .replace("</modified-files>", "")
        )

    def display_compaction_summary(self, summary: str, kept_items_brief: tuple[tuple[str, int, str], ...] = ()) -> None:
        stripped = summary.strip()
        if not stripped:
            return
        stripped = self._strip_summary_tags(stripped)
        self.print(
            Rule(
                Text("Context Compacted", style=ThemeKey.COMPACTION_SUMMARY),
                characters="=",
                style=ThemeKey.LINES,
            )
        )
        self.print()

        # Limit panel width to min(100, terminal_width) minus left indent (2)
        terminal_width = shutil.get_terminal_size().columns
        panel_width = min(100, terminal_width) - 2

        self.console.push_theme(self.themes.markdown_theme)
        panel = Panel(
            NoInsetMarkdown(stripped, code_theme=self.themes.code_theme, style=ThemeKey.COMPACTION_SUMMARY),
            box=box.SIMPLE,
            border_style=ThemeKey.LINES,
            style=ThemeKey.COMPACTION_SUMMARY_PANEL,
            width=panel_width,
        )
        self.print(Padding(panel, (0, 0, 0, MARKDOWN_LEFT_MARGIN)))
        self.console.pop_theme()

        if kept_items_brief:
            # Collect tool call counts (skip User/Assistant entries)
            tool_counts: dict[str, int] = {}
            for item_type, count, _ in kept_items_brief:
                if item_type not in ("User", "Assistant"):
                    tool_counts[item_type] = tool_counts.get(item_type, 0) + count

            if tool_counts:
                parts: list[str] = []
                for tool_type, tool_count in tool_counts.items():
                    if tool_count > 1:
                        parts.append(f"{tool_type} x {tool_count}")
                    else:
                        parts.append(tool_type)
                line = Text()
                line.append("\n  Kept uncompacted: ", style=ThemeKey.COMPACTION_SUMMARY)
                line.append(", ".join(parts), style=ThemeKey.COMPACTION_SUMMARY)
                self.print(line)

        self.print()

    def display_fork_cache_hit_rate(
        self,
        *,
        fork_label: str,
        cache_read_tokens: int,
        cache_creation_tokens: int,
        input_tokens: int,
        cache_hit_rate: float,
        fallback_used: bool,
    ) -> None:
        line = Text()
        line.append(f"  {fork_label} cache: ", style=ThemeKey.METADATA_DIM)
        if fallback_used:
            line.append("not shared (different model)", style=ThemeKey.METADATA_DIM)
        else:
            total = cache_read_tokens + cache_creation_tokens + input_tokens
            hit_pct = round(cache_hit_rate * 100)
            line.append(f"{hit_pct}% hit ", style=ThemeKey.METADATA)
            line.append(
                f"({format_number(cache_read_tokens)} reused / {format_number(total)} total)",
                style=ThemeKey.METADATA_DIM,
            )
        self.print(line)
        self.print()

    def display_handoff(self, summary: str) -> None:
        self.print(
            Rule(
                Text("Context Handed Off", style=ThemeKey.HANDOFF),
                characters="=",
                style=ThemeKey.LINES,
            )
        )
        self.print()

        stripped = self._strip_summary_tags(summary.strip())

        terminal_width = shutil.get_terminal_size().columns
        panel_width = min(100, terminal_width) - 2

        self.console.push_theme(self.themes.markdown_theme)
        panel = Panel(
            NoInsetMarkdown(stripped, code_theme=self.themes.code_theme, style=ThemeKey.HANDOFF_NOTE),
            box=box.SIMPLE,
            border_style=ThemeKey.LINES,
            style=ThemeKey.COMPACTION_SUMMARY_PANEL,
            width=panel_width,
        )
        self.print(Padding(panel, (0, 0, 0, MARKDOWN_LEFT_MARGIN)))
        self.console.pop_theme()
        self.print()

    def display_rewind(
        self,
        checkpoint_id: int,
        note: str,
        rationale: str,
        original_user_message: str,
        messages_discarded: int | None,
    ) -> None:
        self.print(
            Rule(
                Text(f"Rewound to Checkpoint {checkpoint_id}", style=ThemeKey.REWIND),
                characters="=",
                style=ThemeKey.LINES,
            )
        )
        self.print()

        if messages_discarded:
            self.print(Text(f"  Discarded {messages_discarded} messages", style=ThemeKey.REWIND_INFO))

        if rationale:
            self.print(Text("  Rationale:", style=ThemeKey.REWIND_INFO))
            rationale_preview = rationale[:300] + "..." if len(rationale) > 300 else rationale
            self.print(
                Padding(
                    Panel(
                        NoInsetMarkdown(
                            rationale_preview, code_theme=self.themes.code_theme, style=ThemeKey.REWIND_NOTE
                        ),
                        box=box.SIMPLE,
                        border_style=ThemeKey.LINES,
                        style=ThemeKey.REWIND_NOTE,
                    ),
                    (0, 0, 0, 4),
                )
            )

        if original_user_message:
            self.print(Text("  Returned to:", style=ThemeKey.REWIND_INFO))
            msg_preview = (
                original_user_message[:200] + "..." if len(original_user_message) > 200 else original_user_message
            )
            self.print(
                Padding(
                    Panel(
                        Text(msg_preview, style=ThemeKey.REWIND_USER_MESSAGE),
                        box=box.SIMPLE,
                        border_style=ThemeKey.LINES,
                    ),
                    (0, 0, 0, 4),
                )
            )

        self.print(Text("  Summary:", style=ThemeKey.REWIND_INFO))
        note_preview = note[:300] + "..." if len(note) > 300 else note
        self.print(
            Padding(
                Panel(
                    NoInsetMarkdown(note_preview, code_theme=self.themes.code_theme, style=ThemeKey.REWIND_NOTE),
                    box=box.SIMPLE,
                    border_style=ThemeKey.LINES,
                    style=ThemeKey.REWIND_NOTE,
                ),
                (0, 0, 0, 4),
            )
        )

        self.print()

    # ---------------------------------------------------------------------
    # Notifications
    # ---------------------------------------------------------------------

    @staticmethod
    def _is_cancelled_task_finish(event: RenderTaskFinish) -> bool:
        return event.event.task_result.strip().lower() in {"task cancelled", "task canceled"}

    def _maybe_notify_task_finish(self, event: RenderTaskFinish) -> None:
        if self._notifier is None:
            return
        if self.is_sub_agent_session(event.event.session_id):
            return
        if self._is_cancelled_task_finish(event):
            return
        body = self._compact_result_text(event.event.task_result)
        notification = Notification(
            type=NotificationType.AGENT_TASK_COMPLETE,
            title="Task Completed",
            body=body,
        )
        self._notifier.notify(notification)

    def _compact_result_text(self, text: str) -> str | None:
        stripped = text.strip()
        if not stripped:
            return None
        squashed = " ".join(stripped.split())
        if len(squashed) > 200:
            return squashed[:197] + "…"
        return squashed

    # ---------------------------------------------------------------------
    # RenderCommand executor
    # ---------------------------------------------------------------------

    async def execute(self, commands: list[RenderCommand]) -> None:
        finished_tasks_to_notify: list[RenderTaskFinish] = []
        for cmd in commands:
            self._flush_open_blocks_before(cmd)
            log_debug(
                f"{'[Cmd] [Replay]' if self._replay_mode else '[Cmd]'} [{cmd.__class__.__name__}]",
                lambda cmd=cmd: str(cmd),
                debug_type=DebugType.UI_EVENT,
            )
            match cmd:
                case RenderWelcome(event=event):
                    self.display_welcome(event)
                case RenderWelcomeContext(event=event):
                    self.display_welcome_context(event)
                case RenderUserMessage(event=event):
                    self.display_user_message(event)
                case RenderTimeMarker(label=label):
                    self.display_time_marker(label)
                case RenderTaskStart(event=event):
                    self.display_task_start(event)
                case RenderDeveloperMessage(event=event):
                    if self.display_developer_message(event):
                        self._open_continuous_block(event.session_id)
                case RenderNotice(event=event):
                    self.display_notice(event)
                case RenderAwaySummary(event=event):
                    self.display_away_summary(event)
                case RenderSessionStats(event=event):
                    self.display_session_stats(event)
                case RenderContextUsage(event=event):
                    self.display_context_usage(event)
                case RenderBashCommandStart(event=event):
                    self.display_bash_command_start(event)
                case AppendBashCommandOutput(event=event):
                    self.display_bash_command_delta(event)
                case RenderBashCommandEnd(event=event):
                    self.display_bash_command_end(event)
                case StartThinkingStream(session_id=_):
                    if not self._thinking_stream.is_active:
                        self._thinking_stream.start(self._new_thinking_mdstream())
                        if not self._replay_mode:
                            self._thinking_stream.render(transform=c_thinking.normalize_thinking_content)
                case AppendThinking(session_id=_, content=content):
                    if self._thinking_stream.is_active:
                        self._thinking_stream.append(content)
                        if not self._replay_mode:
                            self._flush_thinking()
                case EndThinkingStream(session_id=_):
                    had_content = bool(self._thinking_stream.buffer.strip())
                    finalized = self._thinking_stream.finalize(transform=c_thinking.normalize_thinking_content)
                    if finalized and had_content:
                        self.print()
                case RenderThinkingSummary(
                    session_id=session_id,
                    duration_s=duration_s,
                    char_count=char_count,
                ):
                    with self.session_print_context(session_id):
                        self.print(c_thinking.render_thinking_summary(duration_s, char_count))
                case StartAssistantStream(session_id=_):
                    if not self._assistant_stream.is_active:
                        self._assistant_stream.start(self._new_assistant_mdstream())
                case AppendAssistant(session_id=_, content=content):
                    if self._assistant_stream.is_active:
                        self._assistant_stream.append(content)
                        if not self._replay_mode:
                            self._flush_assistant()
                case EndAssistantStream(session_id=_):
                    had_content = bool(self._assistant_stream.buffer.strip())
                    finalized = self._assistant_stream.finalize()
                    if finalized and had_content:
                        self.print()
                case RenderToolCall(event=event):
                    with self.session_print_context(event.session_id):
                        rendered = self.display_tool_call(event)
                    if rendered:
                        self._open_continuous_block(event.session_id)
                case RenderToolResult(event=event, is_sub_agent_session=is_sub_agent_session):
                    with self.session_print_context(event.session_id):
                        rendered = self.display_tool_call_result(event, is_sub_agent=is_sub_agent_session)
                    if rendered:
                        self._open_continuous_block(event.session_id)
                case RenderCompactToolResult(event=event, arguments=arguments):
                    with self.session_print_context(event.session_id):
                        self.display_compact_tool_result(event, arguments)
                    self._open_continuous_block(event.session_id)
                case RenderTaskMetadata(event=event):
                    self.display_task_metadata(event)
                case RenderTaskFileChangeSummary(event=event):
                    self.display_task_file_change_summary(event)
                case RenderSubAgentBatchSummary(summaries=summaries):
                    self.display_sub_agent_batch_summary(summaries)
                case RenderTaskFinish() as cmd_finish:
                    self.display_task_finish(cmd_finish.event)
                    if (
                        not self._replay_mode
                        and not self.is_sub_agent_session(cmd_finish.event.session_id)
                        and not self._is_cancelled_task_finish(cmd_finish)
                        and self._notifier is not None
                        and self._notifier.enabled
                    ):
                        finished_tasks_to_notify.append(cmd_finish)
                case RenderInterrupt():
                    self.display_interrupt()
                case RenderError(event=event):
                    self.display_error(event)
                case RenderCompactionSummary(summary=summary, kept_items_brief=kept_items_brief):
                    self.display_compaction_summary(summary, kept_items_brief)
                case RenderForkCacheHitRate(
                    fork_label=fork_label,
                    cache_read_tokens=cache_read_tokens,
                    cache_creation_tokens=cache_creation_tokens,
                    input_tokens=input_tokens,
                    cache_hit_rate=cache_hit_rate,
                    fallback_used=fallback_used,
                ):
                    self.display_fork_cache_hit_rate(
                        fork_label=fork_label,
                        cache_read_tokens=cache_read_tokens,
                        cache_creation_tokens=cache_creation_tokens,
                        input_tokens=input_tokens,
                        cache_hit_rate=cache_hit_rate,
                        fallback_used=fallback_used,
                    )
                case RenderHandoff(summary=summary):
                    self.display_handoff(summary)
                case RenderRewind(
                    checkpoint_id=checkpoint_id,
                    note=note,
                    rationale=rationale,
                    original_user_message=original_user_message,
                    messages_discarded=messages_discarded,
                ):
                    self.display_rewind(
                        checkpoint_id=checkpoint_id,
                        note=note,
                        rationale=rationale,
                        original_user_message=original_user_message,
                        messages_discarded=messages_discarded,
                    )
                case SpinnerStart():
                    self.spinner_start()
                case SpinnerStop():
                    self.spinner_stop()
                case SpinnerUpdate(
                    right_text=metadata_text,
                    status_lines=status_lines,
                    separator_text=separator_text,
                    reset_bottom_height=reset_bottom_height,
                ):
                    self.spinner_update(
                        metadata_text,
                        status_lines,
                        separator_text,
                        reset_bottom_height,
                    )
                case PrintBlankLine(session_id=session_id):
                    self._clear_open_blocks()
                    self._print_blank_line(session_id)
                case TaskClockStart():
                    set_task_start()
                case TaskClockClear():
                    clear_task_start()
                case UpdateTerminalTitlePrefix(prefix=prefix, model_name=model_name, session_title=session_title):
                    if is_title_blinking():
                        update_blink_params(model_name=model_name, session_title=session_title)
                    else:
                        update_terminal_title(model_name, prefix=prefix, session_title=session_title)
                case StartTitleBlink(model_name=model_name, session_title=session_title):
                    start_terminal_title_blink(model_name, session_title)
                case StopTitleBlink():
                    stop_terminal_title_blink()
                case _:
                    continue

        if finished_tasks_to_notify:
            # Ghostty applies title changes through a 75ms coalescing timer.
            # Leave room for one 80ms title retry plus that timer before it
            # snapshots the title into the desktop notification.
            await asyncio.sleep(TASK_NOTIFICATION_DELAY_S)
        for cmd_finish in finished_tasks_to_notify:
            self._maybe_notify_task_finish(cmd_finish)

    async def stop(self) -> None:
        self._cancel_bash_live_flush()
        self._cancel_spinner_flush()
        self._flush_open_blocks()
        self._flush_assistant()
        self._flush_thinking()
        stop_terminal_title_blink()
        with contextlib.suppress(Exception):
            self.spinner_stop()
