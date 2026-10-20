"""Bottom-bar UI rendered below the REPL prompt.

Owns the stacked surfaces that appear while an agent is running: the
scrollback gap, status spinner lines, stream tail, and queued follow-ups.
``PromptToolkitInput`` keeps responsibility for the prompt session, pickers,
and clipboard watcher; this module owns everything that renders below the
input.

The enclosing layout aligns the entire prompt to the available bottom row.
Windows use their current content height; spare space belongs above the whole
layout, not to accumulated per-window reservations or delayed collapse timers.
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
from prompt_toolkit.utils import get_cwidth

from klaude_code.const import STATUS_WAITING_TEXT
from klaude_code.tui.commands import PromptStatusLine
from klaude_code.tui.input.pt_theme import CLASS_META, CLASS_TOOL_RESULT, CLASS_USER_INPUT
from klaude_code.tui.terminal.tty_state import stdout_writable

_STATUS_SPINNER_FRAMES = ("·  ", "·· ", "···", " ··", "  ·", "   ")
_STATUS_SPINNER_INTERVAL_SECONDS = 0.12
_STARTUP_LOADING_TEXT = "Preparing session…"

# Refresh the renderer-side status snapshot every N spinner ticks instead of
# every tick. The snapshot only changes with the elapsed-time clock (second
# granularity), while each refresh re-renders the status block through Rich;
# ~0.48s cadence keeps the clock fresh at a fraction of the cost.
_STATUS_REFRESH_EVERY_TICKS = 4


class PromptBottomBar:
    def __init__(
        self,
        *,
        invalidate: Callable[[], None],
        refresh_status: Callable[[], None] | None = None,
    ) -> None:
        self._invalidate = invalidate
        self._refresh_status = refresh_status

        self._stream_lines: tuple[str, ...] = ()
        self._stream_style_class: str = CLASS_TOOL_RESULT
        self._stream_reserved_line_count: int = 0
        self._status_lines: tuple[PromptStatusLine, ...] = ()
        self._metadata_footer_lines: tuple[str, ...] = ()
        self._status_reserved_line_count: int = 0
        self._running_separator_label: str | None = None
        self._startup_loading = False
        self._startup_loading_title: str | None = None
        self._agent_running = False
        self._pending_messages: tuple[str, ...] = ()

        self._status_spinner_task: asyncio.Task[None] | None = None
        self._status_spinner_frame: int = 0

    # ---- public mutators -------------------------------------------------

    def set_stream_lines(
        self,
        lines: tuple[str, ...],
        *,
        end_of_stream: bool = False,
        style_class: str = CLASS_TOOL_RESULT,
    ) -> None:
        stream_lines = tuple(line for line in lines if line.strip())

        if end_of_stream:
            stream_lines = ()
        new_reserved = len(stream_lines)
        if (
            stream_lines == self._stream_lines
            and new_reserved == self._stream_reserved_line_count
            and style_class == self._stream_style_class
        ):
            return
        self._stream_lines = stream_lines
        self._stream_style_class = style_class
        self._stream_reserved_line_count = new_reserved
        self._invalidate()

    def set_status_lines(
        self,
        lines: tuple[PromptStatusLine, ...],
        *,
        separator_text: str | None = None,
        reset_bottom_height: bool = False,
    ) -> None:
        status_lines = tuple(line for line in lines if line.text.strip())
        visible_status_lines = tuple(line for line in status_lines if line.kind != "metadata")
        metadata_footer_lines = tuple(line.text for line in status_lines if line.kind == "metadata")
        # Kept in the sink contract for callers; geometry no longer needs a reset.
        del reset_bottom_height
        self._status_reserved_line_count = len(visible_status_lines)
        if status_lines == self._status_lines and separator_text == self._running_separator_label:
            if metadata_footer_lines:
                self._metadata_footer_lines = metadata_footer_lines
            if visible_status_lines or self._startup_loading or self._agent_running:
                self._ensure_status_spinner()
            else:
                self._cancel_status_spinner()
            return

        self._status_lines = status_lines
        if metadata_footer_lines:
            self._metadata_footer_lines = metadata_footer_lines
        self._running_separator_label = separator_text
        if visible_status_lines:
            self._status_reserved_line_count = max(1, len(visible_status_lines))
            self._ensure_status_spinner()
        elif self._startup_loading or self._agent_running:
            self._ensure_status_spinner()
        else:
            self._cancel_status_spinner()
        self._invalidate()

    def set_startup_loading(self, loading: bool) -> None:
        if self._startup_loading == loading:
            return

        self._startup_loading = loading
        if loading or self._visible_status_lines() or self._agent_running:
            self._ensure_status_spinner()
        else:
            self._cancel_status_spinner()
        self._invalidate()

    def set_agent_running(self, running: bool) -> None:
        if self._agent_running == running:
            return

        self._agent_running = running
        if running or self._visible_status_lines() or self._startup_loading:
            self._ensure_status_spinner()
        else:
            self._cancel_status_spinner()
        self._invalidate()

    def set_startup_loading_title(self, title: str | None) -> None:
        title = (title or "").strip() or None
        if title == self._startup_loading_title:
            return
        self._startup_loading_title = title
        if self._startup_loading:
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
        rows += self._pending_block_height()
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
            height=self._status_head_height,
            dont_extend_height=True,
        )
        # Child-agent rows and the task footer sit below the live tail, so the
        # main agent's thinking preview stays directly under its own status line.
        status_tail_window = Window(
            content=FormattedTextControl(self._get_status_tail_fragments),
            height=lambda: len(self._status_tail_lines()),
            dont_extend_height=True,
        )
        queue_window = Window(
            content=FormattedTextControl(self._get_pending_message_fragments),
            height=self._pending_window_height,
            dont_extend_height=True,
        )

        stream_visible = Condition(lambda: self._stream_reserved_line_count > 0)
        return [
            _spacer(),
            status_window,
            ConditionalContainer(stream_window, filter=stream_visible),
            ConditionalContainer(status_tail_window, filter=Condition(lambda: bool(self._status_tail_lines()))),
            ConditionalContainer(_spacer(), filter=Condition(lambda: bool(self._pending_messages))),
            ConditionalContainer(queue_window, filter=Condition(lambda: bool(self._pending_messages))),
        ]

    # ---- lifecycle -------------------------------------------------------

    def stop(self) -> None:
        self._cancel_status_spinner()

    # ---- fragment generators --------------------------------------------

    def _get_stream_fragments(self) -> StyleAndTextTuples:
        try:
            columns = get_app().output.get_size().columns
        except Exception:
            columns = 80
        fragments: StyleAndTextTuples = []
        for index, line in enumerate(self._stream_lines):
            if index:
                fragments.append(("", "\n"))
            fragments.append((self._stream_style_class, _truncate_line(line, max(1, columns))))
        return fragments

    def _status_window_height(self) -> int:
        return max(1, len(self._visible_status_lines()), self._status_reserved_line_count)

    def _visible_status_lines(self) -> tuple[PromptStatusLine, ...]:
        return tuple(line for line in self._status_lines if line.kind != "metadata")

    def _status_head_lines(self) -> tuple[PromptStatusLine, ...]:
        """Leading rows that carry the plain spinner: the main agent and `/btw` asides."""
        lines = self._visible_status_lines()
        count = 0
        while count < len(lines) and lines[count].show_spinner and lines[count].inline_spinner_style is None:
            count += 1
        return lines[:count]

    def _status_tail_lines(self) -> tuple[PromptStatusLine, ...]:
        return self._visible_status_lines()[len(self._status_head_lines()) :]

    def _status_head_height(self) -> int:
        # The reservation pads the head, so the tail and the input below never move.
        tail = len(self._status_tail_lines())
        return max(0 if tail else 1, self._status_window_height() - tail)

    def _pending_window_height(self) -> int:
        return len(self._pending_messages) + 1

    def _pending_block_height(self) -> int:
        if not self._pending_messages:
            return 0
        # Leading spacer + queue window; no trailing blank before the input rule.
        return self._pending_window_height() + 1

    def _get_status_fragments(self) -> StyleAndTextTuples:
        fragments: StyleAndTextTuples = []
        spinner = self._spinner_frame()
        visible_lines = self._status_head_lines()
        show_waiting = bool(not self._visible_status_lines() and not self._startup_loading and self._agent_running)
        content_line_count = len(visible_lines) or int(self._startup_loading or show_waiting)
        top_padding = self._status_head_height() - content_line_count
        if content_line_count and top_padding > 0:
            fragments.append(("", "\n" * top_padding))
        if not visible_lines:
            if self._startup_loading:
                loading_text = _STARTUP_LOADING_TEXT
                if self._startup_loading_title:
                    loading_text = f"Preparing session · {_truncate_line(self._startup_loading_title, 48)}…"
                fragments.extend([(CLASS_META, f"{spinner} "), (CLASS_META, loading_text)])
                return fragments
            # A task has been submitted but no status snapshot has arrived yet
            # (agent runtime is still starting up). Show the waiting text
            # immediately so submission feedback is not tied to backend
            # startup latency.
            if show_waiting:
                fragments.extend([(CLASS_META, f"{spinner} "), (CLASS_META, STATUS_WAITING_TEXT)])
            return fragments
        return self._append_status_line_fragments(fragments, visible_lines)

    def _get_status_tail_fragments(self) -> StyleAndTextTuples:
        return self._append_status_line_fragments([], self._status_tail_lines())

    def _spinner_frame(self) -> str:
        return _STATUS_SPINNER_FRAMES[self._status_spinner_frame % len(_STATUS_SPINNER_FRAMES)]

    def _append_status_line_fragments(
        self, fragments: StyleAndTextTuples, lines: tuple[PromptStatusLine, ...]
    ) -> StyleAndTextTuples:
        spinner = self._spinner_frame()
        for index, line in enumerate(lines):
            if index:
                fragments.append(("", "\n"))
            if line.inline_spinner_style is not None:
                fragments.append((line.inline_spinner_style, f"{spinner} "))
            elif line.show_spinner:
                fragments.append((CLASS_META, f"{spinner} "))
            if line.fragments:
                fragments.extend(line.fragments)
            else:
                fragments.append((CLASS_META, line.text))
        return fragments

    def _get_pending_message_fragments(self) -> StyleAndTextTuples:
        count = len(self._pending_messages)
        fragments: StyleAndTextTuples = [(CLASS_META, f"Steering ({count} pending) · next safe step · ↑ to edit.")]
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
            if not self._visible_status_lines() and not self._startup_loading and not self._agent_running:
                return
            # Skip animation frames while the tty is not draining: the redraw
            # this invalidate triggers would block the event loop on a full
            # pty buffer, freezing the display consumer and the LLM stream.
            if not stdout_writable():
                continue
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


def _truncate_line(line: str, max_width: int) -> str:
    width = sum(get_cwidth(char) for char in line)
    if width <= max_width:
        return line
    if max_width <= 0:
        return ""
    if max_width == 1:
        return "…"

    remaining = max_width - get_cwidth("…")
    result: list[str] = []
    for char in line:
        char_width = get_cwidth(char)
        if char_width > remaining:
            break
        result.append(char)
        remaining -= char_width
    return f"{''.join(result)}…"
