"""Publish `HistoryAppendedEvent` when the session store flushes a batch.

``JsonlSessionWriter`` writes in a worker thread (``asyncio.to_thread``), so
its "batch landed" notification cannot touch the event bus directly. This
bridge hands the notification back to the server loop and publishes it there.

The viewer reads the ledger over REST, not from the event stream: this event
is only the "there is more on disk" signal that makes it pull the tail
increment (``/api/web/sessions/{id}/history?after_line=``). It carries no
history content, so it is skipped from the attach tape (see
``session_tape._SKIPPED_EVENT_TYPES``) — replaying a stale line count to a
late attach would only trigger a redundant fetch.
"""

from __future__ import annotations

import asyncio

from klaude_code.control.event_bus import EventBus
from klaude_code.protocol import events


class HistoryAppendBridge:
    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus
        self._loop: asyncio.AbstractEventLoop | None = None
        # Strong refs: a bare create_task can be collected mid-flight.
        self._tasks: set[asyncio.Task[None]] = set()

    def attach_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def on_history_written(self, session_id: str, line_count: int) -> None:
        """Writer-thread entry point (``register_session_history_observer``)."""
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        try:
            loop.call_soon_threadsafe(self._publish, session_id, line_count)
        except RuntimeError:
            # The loop closed between the check and the hand-off.
            return

    def _publish(self, session_id: str, line_count: int) -> None:
        event = events.HistoryAppendedEvent(session_id=session_id, line_count=line_count)
        task = asyncio.ensure_future(self._event_bus.publish(event))
        self._tasks.add(task)
        _ = task.add_done_callback(self._tasks.discard)
