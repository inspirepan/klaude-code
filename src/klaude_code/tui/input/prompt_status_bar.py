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
from prompt_toolkit.utils import get_cwidth

from klaude_code.tui.commands import PromptStatusLine
from klaude_code.tui.input.pt_theme import CLASS_META, CLASS_USER_INPUT, CLASS_USER_INPUT_RULE

_STATUS_SPINNER_FRAMES = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")
_STATUS_SPINNER_INTERVAL_SECONDS = 0.12


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
        self._stream_reserved_line_count: int = 0
        self._status_lines: tuple[PromptStatusLine, ...] = ()
        self._status_reserved_line_count: int = 0
        self._running_separator_label: str | None = None
        self._pending_messages: tuple[str, ...] = ()

        self._status_spinner_task: asyncio.Task[None] | None = None
        self._status_spinner_frame: int = 0

    # ---- public mutators -------------------------------------------------

    def set_stream_lines(self, lines: tuple[str, ...], *, end_of_stream: bool = False) -> None:
        stream_lines = tuple(line for line in lines if line.strip())

        # End-of-stream: collapse the reserved area entirely.
        if end_of_stream:
            if not self._stream_lines and self._stream_reserved_line_count == 0:
                return
            self._stream_lines = ()
            self._stream_reserved_line_count = 0
            self._invalidate()
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

    def set_status_lines(
        self,
        lines: tuple[PromptStatusLine, ...],
        *,
        separator_text: str | None = None,
    ) -> None:
        status_lines = tuple(line for line in lines if line.text.strip())
        if status_lines == self._status_lines and separator_text == self._running_separator_label:
            if status_lines:
                self._ensure_status_spinner()
            else:
                self._cancel_status_spinner()
            return

        self._status_lines = status_lines
        self._running_separator_label = separator_text
        if self._status_lines:
            self._status_reserved_line_count = max(self._status_reserved_line_count, len(self._status_lines))
            self._ensure_status_spinner()
        else:
            self._status_reserved_line_count = 0
            self._cancel_status_spinner()
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

    # ---- layout integration ---------------------------------------------

    def build_containers(self, *, is_agent_running: Callable[[], bool]) -> list[Container]:
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
        running_separator_window = Window(
            content=FormattedTextControl(self._get_running_separator_fragments),
            height=1,
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
            ConditionalContainer(
                _spacer(),
                filter=Condition(lambda: bool(self._status_lines) and self._stream_reserved_line_count == 0),
            ),
            ConditionalContainer(status_window, filter=Condition(lambda: bool(self._status_lines))),
            ConditionalContainer(_spacer(), filter=Condition(lambda: bool(self._status_lines))),
            ConditionalContainer(running_separator_window, filter=Condition(is_agent_running)),
            ConditionalContainer(_spacer(), filter=Condition(is_agent_running)),
            ConditionalContainer(queue_window, filter=Condition(lambda: bool(self._pending_messages))),
            ConditionalContainer(_spacer(), filter=Condition(lambda: bool(self._pending_messages))),
        ]

    # ---- lifecycle -------------------------------------------------------

    def stop(self) -> None:
        self._cancel_status_spinner()

    # ---- fragment generators --------------------------------------------

    def _get_stream_fragments(self) -> StyleAndTextTuples:
        fragments: StyleAndTextTuples = []
        for index, line in enumerate(self._stream_lines):
            if index:
                fragments.append(("", "\n"))
            fragments.append((CLASS_META, line))
        return fragments

    def _status_window_height(self) -> int:
        return max(len(self._status_lines), self._status_reserved_line_count)

    def _get_status_fragments(self) -> StyleAndTextTuples:
        fragments: StyleAndTextTuples = []
        spinner = _STATUS_SPINNER_FRAMES[self._status_spinner_frame % len(_STATUS_SPINNER_FRAMES)]
        for index, line in enumerate(self._status_lines):
            if index:
                fragments.append(("", "\n"))
            if line.kind != "metadata":
                fragments.append((CLASS_META, f"{spinner} "))
            fragments.append((CLASS_META, line.text))
        return fragments

    def _get_running_separator_fragments(self) -> StyleAndTextTuples:
        try:
            columns = get_app().output.get_size().columns
        except Exception:
            columns = 80
        label = self._running_separator_label
        if not label:
            return [(CLASS_USER_INPUT_RULE, "╸" * max(1, columns))]

        label_width = get_cwidth(label)
        if label_width + 1 >= columns:
            return [(CLASS_USER_INPUT_RULE, label)]
        return [(CLASS_USER_INPUT_RULE, f"{'╸' * max(1, columns - label_width - 1)} {label}")]

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
        while True:
            await asyncio.sleep(_STATUS_SPINNER_INTERVAL_SECONDS)
            if not self._status_lines:
                return
            self._status_spinner_frame = (self._status_spinner_frame + 1) % len(_STATUS_SPINNER_FRAMES)
            if self._refresh_status is not None:
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
