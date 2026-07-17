"""Bottom-bar UI rendered below the REPL prompt.

Owns the four stacked surfaces that appear while an agent is running:
stream tail, status spinner lines, running separator, and queued follow-ups.
``PromptToolkitInput`` keeps responsibility for the prompt session, pickers,
and clipboard watcher; this module owns everything that renders below the
input.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable

from prompt_toolkit.application.current import get_app
from prompt_toolkit.filters import Condition
from prompt_toolkit.formatted_text import StyleAndTextTuples
from prompt_toolkit.layout.containers import ConditionalContainer, Container, Window
from prompt_toolkit.layout.controls import FormattedTextControl

from klaude_code.const import STATUS_WAITING_TEXT
from klaude_code.tui.commands import PromptStatusLine
from klaude_code.tui.input.pt_theme import CLASS_LINES, CLASS_META, CLASS_USER_INPUT

_STATUS_SPINNER_FRAMES = ("·  ", "·· ", "···", " ··", "  ·", "   ")
_STATUS_SPINNER_INTERVAL_SECONDS = 0.12

# Refresh the renderer-side status snapshot every N spinner ticks instead of
# every tick. The snapshot only changes with the elapsed-time clock (second
# granularity), while each refresh re-renders the status block through Rich;
# ~0.48s cadence keeps the clock fresh at a fraction of the cost.
_STATUS_REFRESH_EVERY_TICKS = 4

# How long to hold the stream area's reserved height after an end-of-stream
# signal before truly collapsing it. Adjacent post-stream events
# (TaskMetadata, TaskFinish) typically arrive within a few milliseconds;
# keeping the reservation while their scrollback writes drain through the
# StdoutProxy queue prevents prompt-toolkit from briefly painting the
# input field right under the last assistant message.
_STREAM_RESERVATION_HOLD_SECONDS = 0.6
_STATUS_RESERVATION_HOLD_SECONDS = 0.6


class PromptBottomBar:
    def __init__(
        self,
        *,
        invalidate: Callable[[], None],
        refresh_status: Callable[[], None] | None = None,
        is_agent_running: Callable[[], bool] | None = None,
    ) -> None:
        self._invalidate = invalidate
        self._refresh_status = refresh_status
        self._is_agent_running = is_agent_running

        self._stream_lines: tuple[str, ...] = ()
        self._stream_reserved_line_count: int = 0
        self._stream_collapse_handle: asyncio.TimerHandle | None = None
        self._status_lines: tuple[PromptStatusLine, ...] = ()
        self._metadata_footer_lines: tuple[str, ...] = ()
        self._status_reserved_line_count: int = 0
        self._status_collapse_handle: asyncio.TimerHandle | None = None
        self._running_separator_label: str | None = None
        self._pending_messages: tuple[str, ...] = ()

        self._status_spinner_task: asyncio.Task[None] | None = None
        self._status_spinner_frame: int = 0

    # ---- public mutators -------------------------------------------------

    def set_stream_lines(self, lines: tuple[str, ...], *, end_of_stream: bool = False) -> None:
        stream_lines = tuple(line for line in lines if line.strip())

        # Any new state cancels a pending delayed collapse — either we're
        # going to collapse anyway, or we have new content that resets the
        # debounce.
        self._cancel_pending_stream_collapse()

        # End-of-stream: clear the visible content immediately but defer the
        # height collapse so adjacent post-stream events (TaskMetadata,
        # TaskFinish) can land in scrollback first. Without the delay,
        # prompt-toolkit's spinner-driven redraw fires between events and
        # paints the input field right under the last assistant message
        # before metadata/finish render.
        if end_of_stream:
            if not self._stream_lines and self._stream_reserved_line_count == 0:
                return
            self._stream_lines = ()
            self._invalidate()
            self._schedule_stream_collapse()
            return

        # Otherwise hold a high-water reservation so transient frame-to-frame
        # height shrinking (e.g. MarkdownStream stable/live re-balancing) does
        # not flicker the layout. prompt-toolkit pads the difference with
        # blanks for free since the Window has a fixed height.
        new_reserved = max(self._stream_reserved_line_count, len(stream_lines))
        if stream_lines == self._stream_lines and new_reserved == self._stream_reserved_line_count:
            return
        self._stream_lines = stream_lines
        self._stream_reserved_line_count = new_reserved
        self._invalidate()

    def _cancel_pending_stream_collapse(self) -> None:
        handle = self._stream_collapse_handle
        if handle is None:
            return
        self._stream_collapse_handle = None
        with contextlib.suppress(Exception):
            handle.cancel()

    def _schedule_stream_collapse(self) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # No running loop (non-interactive paths e.g. replay tests):
            # collapse immediately so behavior matches the synchronous
            # contract.
            self._stream_reserved_line_count = 0
            self._invalidate()
            return
        self._stream_collapse_handle = loop.call_later(
            _STREAM_RESERVATION_HOLD_SECONDS,
            self._do_stream_collapse,
        )

    def _do_stream_collapse(self) -> None:
        self._stream_collapse_handle = None
        if self._stream_reserved_line_count == 0:
            return
        self._stream_reserved_line_count = 0
        self._invalidate()

    def set_status_lines(
        self,
        lines: tuple[PromptStatusLine, ...],
        *,
        separator_text: str | None = None,
    ) -> None:
        status_lines = tuple(line for line in lines if line.text.strip())
        visible_status_lines = tuple(line for line in status_lines if line.kind != "metadata")
        metadata_footer_lines = tuple(line.text for line in status_lines if line.kind == "metadata")
        if status_lines == self._status_lines and separator_text == self._running_separator_label:
            if metadata_footer_lines:
                self._metadata_footer_lines = metadata_footer_lines
            if visible_status_lines:
                self._ensure_status_spinner()
            else:
                self._cancel_status_spinner()
            return

        self._cancel_pending_status_collapse()
        self._status_lines = status_lines
        if metadata_footer_lines:
            self._metadata_footer_lines = metadata_footer_lines
        self._running_separator_label = separator_text
        if visible_status_lines:
            self._status_reserved_line_count = max(self._status_reserved_line_count, len(visible_status_lines))
            self._ensure_status_spinner()
        else:
            self._cancel_status_spinner()
            if self._status_reserved_line_count > 0:
                self._schedule_status_collapse()
        self._invalidate()

    def _cancel_pending_status_collapse(self) -> None:
        handle = self._status_collapse_handle
        if handle is None:
            return
        self._status_collapse_handle = None
        with contextlib.suppress(Exception):
            handle.cancel()

    def _schedule_status_collapse(self) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            self._status_reserved_line_count = 0
            return
        self._status_collapse_handle = loop.call_later(
            _STATUS_RESERVATION_HOLD_SECONDS,
            self._do_status_collapse,
        )

    def _do_status_collapse(self) -> None:
        self._status_collapse_handle = None
        if self._status_reserved_line_count == 0:
            return
        self._status_reserved_line_count = 0
        self._invalidate()

    def set_pending_messages(self, messages: tuple[str, ...]) -> None:
        pending_messages = tuple(message for message in messages if message.strip())
        if pending_messages == self._pending_messages:
            return
        self._pending_messages = pending_messages
        self._invalidate()

    @property
    def has_pending_messages(self) -> bool:
        return bool(self._pending_messages)

    @property
    def running_separator_label(self) -> str | None:
        return self._running_separator_label

    @property
    def metadata_footer_lines(self) -> tuple[str, ...]:
        return self._metadata_footer_lines

    def reserved_layout_rows(self) -> int:
        """Return the current number of rows reserved by build_containers()."""

        rows = max(0, self._stream_reserved_line_count) + 1
        rows += self._status_window_height()
        if self._pending_messages:
            rows += len(self._pending_messages) + 2
        return rows

    # ---- layout integration ---------------------------------------------

    def build_containers(self) -> list[Container]:
        stream_window = Window(
            content=FormattedTextControl(self._get_stream_fragments),
            height=lambda: self._stream_reserved_line_count,
            dont_extend_height=True,
        )
        status_window = Window(
            content=FormattedTextControl(self._get_status_fragments),
            height=self._status_window_height,
            dont_extend_height=True,
        )
        queue_window = Window(
            content=FormattedTextControl(self._get_pending_message_fragments),
            height=lambda: len(self._pending_messages) + 1,
            dont_extend_height=True,
        )

        stream_visible = Condition(lambda: self._stream_reserved_line_count > 0)
        return [
            ConditionalContainer(stream_window, filter=stream_visible),
            ConditionalContainer(_spacer(), filter=stream_visible),
            ConditionalContainer(_spacer(), filter=Condition(lambda: self._stream_reserved_line_count == 0)),
            status_window,
            ConditionalContainer(queue_window, filter=Condition(lambda: bool(self._pending_messages))),
            ConditionalContainer(_spacer(), filter=Condition(lambda: bool(self._pending_messages))),
        ]

    # ---- lifecycle -------------------------------------------------------

    def stop(self) -> None:
        self._cancel_status_spinner()
        self._cancel_pending_stream_collapse()
        self._cancel_pending_status_collapse()

    # ---- fragment generators --------------------------------------------

    def _get_stream_fragments(self) -> StyleAndTextTuples:
        fragments: StyleAndTextTuples = []
        for index, line in enumerate(self._stream_lines):
            if index:
                fragments.append(("", "\n"))
            fragments.append((CLASS_META, line))
        return fragments

    def _status_window_height(self) -> int:
        return max(1, len(self._visible_status_lines()), self._status_reserved_line_count)

    def _visible_status_lines(self) -> tuple[PromptStatusLine, ...]:
        return tuple(line for line in self._status_lines if line.kind != "metadata")

    def _get_status_fragments(self) -> StyleAndTextTuples:
        fragments: StyleAndTextTuples = []
        spinner = _STATUS_SPINNER_FRAMES[self._status_spinner_frame % len(_STATUS_SPINNER_FRAMES)]
        visible_lines = self._visible_status_lines()
        if not visible_lines:
            # A task has been submitted but no status snapshot has arrived yet
            # (agent runtime is still starting up). Show the waiting text
            # immediately so submission feedback is not tied to backend
            # startup latency.
            if self._is_agent_running is not None and self._is_agent_running():
                return [(CLASS_META, f"{spinner} "), (CLASS_META, STATUS_WAITING_TEXT)]
            return fragments
        for index, line in enumerate(visible_lines):
            if index:
                fragments.append(("", "\n"))
            fragments.append((CLASS_META, f"{spinner} "))
            fragments.append((CLASS_META, line.text))
        return fragments

    def _get_running_separator_fragments(self) -> StyleAndTextTuples:
        try:
            columns = get_app().output.get_size().columns
        except Exception:
            columns = 80
        return [(CLASS_LINES, "─" * max(1, columns))]

    def _get_pending_message_fragments(self) -> StyleAndTextTuples:
        count = len(self._pending_messages)
        fragments: StyleAndTextTuples = [(CLASS_META, f"Queued follow-up message ({count} pending) · ↑ to edit.")]
        for index, message in enumerate(self._pending_messages, start=1):
            preview = " ".join(message.split())
            fragments.append(("", "\n"))
            fragments.append((CLASS_META, f"  {index}. "))
            fragments.append((CLASS_USER_INPUT, preview))
        return fragments

    # ---- spinner task ----------------------------------------------------

    async def _spin_status(self) -> None:
        tick = 0
        while True:
            await asyncio.sleep(_STATUS_SPINNER_INTERVAL_SECONDS)
            if not self._status_lines:
                return
            self._status_spinner_frame = (self._status_spinner_frame + 1) % len(_STATUS_SPINNER_FRAMES)
            tick += 1
            if self._refresh_status is not None and tick % _STATUS_REFRESH_EVERY_TICKS == 0:
                with contextlib.suppress(Exception):
                    self._refresh_status()
            with contextlib.suppress(Exception):
                self._invalidate()

    def _ensure_status_spinner(self) -> None:
        if self._status_spinner_task is not None and not self._status_spinner_task.done():
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._status_spinner_task = loop.create_task(self._spin_status())

    def _cancel_status_spinner(self) -> None:
        task = self._status_spinner_task
        if task is None:
            return
        self._status_spinner_task = None
        if not task.done():
            task.cancel()


def _spacer() -> Window:
    return Window(content=FormattedTextControl(""), height=1, dont_extend_height=True)
