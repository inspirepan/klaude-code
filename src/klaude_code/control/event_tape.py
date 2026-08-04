"""Process-local recording of the events a display has consumed.

The interactive TUI re-renders its transcript (Ctrl+O detail toggle, /refresh)
by replaying this tape through the display state machine. The tape holds
exactly what the display consumed, in order, so a rebuild reproduces the
screen — including the in-flight turn that persisted history does not cover
yet. The tape is display-agnostic on purpose: the server can host its own
instance fed from the relay bus to backfill mid-run attaches.

The tape inherits the display's delivery guarantees: if the event bus drops a
subscriber on overflow, the dropped events are missing from both the screen
and the tape, so a rebuild still matches what the user saw.
"""

from __future__ import annotations

from klaude_code.protocol import events

# Streaming deltas dominate event volume; consecutive deltas of the same kind
# collapse into one event so tape memory stays proportional to transcript
# size. The display state machine treats delta content as a pure append, so
# the merge is semantically lossless.
_MERGEABLE_DELTA_TYPES = (
    events.AssistantTextDeltaEvent,
    events.ThinkingDeltaEvent,
    events.BashCommandOutputDeltaEvent,
    events.ToolOutputDeltaEvent,
)


def apply_retractions(items: list[events.Event]) -> list[events.Event]:
    """Project a tape snapshot with retracted turns hidden.

    A ``UserMessageRetractedEvent`` hides its whole turn: the nearest
    preceding ``UserMessageEvent`` with matching content and everything
    recorded after it (thinking stream, interrupt, partial metadata) up to
    the marker itself. The tape stays a faithful record of consumption; this
    is a render-time view applied before every rebuild. A marker whose
    anchor is missing (mismatched content or tape cleared by a session
    switch) hides nothing.
    """
    result: list[events.Event] = []
    for event in items:
        if not isinstance(event, events.UserMessageRetractedEvent):
            result.append(event)
            continue
        for idx in range(len(result) - 1, -1, -1):
            item = result[idx]
            if not isinstance(item, events.UserMessageEvent):
                continue
            if item.session_id == event.session_id and item.content == event.content:
                del result[idx:]
            break
    return result


class EventTape:
    """Append-only event recording with delta coalescing and session scoping."""

    def __init__(self) -> None:
        self._items: list[events.Event] = []
        self._pending_delta: events.Event | None = None
        self._pending_chunks: list[str] = []
        self._pending_timestamp: float = 0.0
        self._session_id: str | None = None

    def __len__(self) -> int:
        return len(self._items) + (1 if self._pending_delta is not None else 0)

    def record(self, event: events.Event) -> None:
        """Append a consumed event, merging consecutive streaming deltas."""
        if isinstance(event, events.WelcomeEvent):
            # Mirrors DisplayStateMachine._handle_WelcomeEvent: a new session id
            # starts a new terminal view (/new, /switch), so the old tape no
            # longer describes the screen.
            if self._session_id is not None and self._session_id != event.session_id:
                self.clear()
            self._session_id = event.session_id
        if isinstance(event, events.ReplayHistoryEvent):
            # History replay is already a flat batch; store the inner events so
            # a rebuild is one uniform pass over the tape.
            for item in event.events:
                self.record(item)
            return
        if isinstance(event, _MERGEABLE_DELTA_TYPES):
            if self._pending_delta is not None and self._merge_key(event) == self._merge_key(self._pending_delta):
                self._pending_chunks.append(event.content)
                self._pending_timestamp = event.timestamp
                return
            self._flush_pending()
            self._pending_delta = event
            self._pending_chunks = [event.content]
            self._pending_timestamp = event.timestamp
            return
        self._flush_pending()
        self._items.append(event)

    def snapshot(self) -> list[events.Event]:
        """The recorded events in consumption order."""
        self._flush_pending()
        return list(self._items)

    def clear(self) -> None:
        self._items = []
        self._pending_delta = None
        self._pending_chunks = []

    @staticmethod
    def _merge_key(event: events.Event) -> tuple[object, ...]:
        return (type(event), event.session_id, getattr(event, "tool_call_id", None))

    def _flush_pending(self) -> None:
        pending = self._pending_delta
        if pending is None:
            return
        self._pending_delta = None
        chunks = self._pending_chunks
        self._pending_chunks = []
        if len(chunks) == 1:
            self._items.append(pending)
            return
        self._items.append(
            pending.model_copy(update={"content": "".join(chunks), "timestamp": self._pending_timestamp})
        )
