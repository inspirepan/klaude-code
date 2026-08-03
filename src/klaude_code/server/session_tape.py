"""Server-side per-session envelope tapes for attach replay.

Each session actor gets a tape recording every envelope published for it,
fed synchronously from the event bus publish path (`set_publish_listener`),
so a snapshot taken between two publishes never sees a half-delivered event.

Splice invariant: a tape is created lazily on the first recorded envelope,
capturing ``base_history_len`` — the session's persisted item count at that
moment. Every later event for the session is on the tape, so an attach
replay of ``get_history_item(limit=base_history_len)`` followed by the tape
snapshot followed by the live stream (deduplicated by ``event_seq``) is
complete, ordered, and free of duplicates — even across actor reclaim and
rehydration, because reclaim only happens after the session flushed to disk.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from klaude_code.protocol import events

# Consecutive streaming deltas of the same kind collapse into one envelope so
# tape memory stays proportional to transcript size (mirrors
# control/event_tape.py; the display treats delta content as a pure append).
_MERGEABLE_DELTA_TYPES = (
    events.AssistantTextDeltaEvent,
    events.ThinkingDeltaEvent,
    events.BashCommandOutputDeltaEvent,
    events.ToolOutputDeltaEvent,
)

# Not recorded: the attach handshake synthesizes a fresh WelcomeEvent per
# connection, and replay batches never travel through the live bus.
_SKIPPED_EVENT_TYPES = (
    events.WelcomeEvent,
    events.WelcomeContextEvent,
    events.ReplayHistoryEvent,
    events.EndEvent,
)


@dataclass(frozen=True)
class TapeCut:
    """An atomic snapshot of a session tape for attach replay splicing."""

    base_history_len: int
    envelopes: tuple[events.EventEnvelope, ...]
    max_event_seq: int


class _SessionTape:
    def __init__(self, base_history_len: int) -> None:
        self.base_history_len = base_history_len
        self._items: list[events.EventEnvelope] = []
        self.max_event_seq = 0

    def record(self, envelope: events.EventEnvelope) -> None:
        self.max_event_seq = max(self.max_event_seq, envelope.event_seq)
        event = envelope.event
        if isinstance(event, _MERGEABLE_DELTA_TYPES) and self._items:
            last = self._items[-1]
            if type(last.event) is type(event) and getattr(last.event, "tool_call_id", None) == getattr(
                event, "tool_call_id", None
            ):
                merged_event = event.model_copy(
                    update={"content": getattr(last.event, "content", "") + getattr(event, "content", "")}
                )
                self._items[-1] = envelope.model_copy(update={"event": merged_event})
                return
        self._items.append(envelope)

    def cut(self) -> TapeCut:
        return TapeCut(
            base_history_len=self.base_history_len,
            envelopes=tuple(self._items),
            max_event_seq=self.max_event_seq,
        )

    def last_event(self) -> events.Event | None:
        if not self._items:
            return None
        return self._items[-1].event

    def reset(self, history_len: int) -> None:
        # max_event_seq stays monotonic: an attach spanning the reset must
        # keep skipping live events the (now-cleared) tape had covered.
        self.base_history_len = history_len
        self._items.clear()


class SessionEventTapes:
    """Registry of per-session tapes, fed from the bus publish listener."""

    def __init__(self, get_history_len: Callable[[str], int | None]) -> None:
        self._get_history_len = get_history_len
        self._tapes: dict[str, _SessionTape] = {}

    def record(self, envelope: events.EventEnvelope) -> None:
        session_id = envelope.session_id
        if not session_id or session_id == "__app__":
            return
        if isinstance(envelope.event, _SKIPPED_EVENT_TYPES):
            return
        tape = self._tapes.get(session_id)
        if tape is None:
            # No in-memory session yet (e.g. sub-agent child sessions): skip;
            # attach never targets a session the registry cannot resolve.
            history_len = self._get_history_len(session_id)
            if history_len is None:
                return
            tape = _SessionTape(base_history_len=history_len)
            self._tapes[session_id] = tape
        tape.record(envelope)

    def cut(self, session_id: str) -> TapeCut | None:
        tape = self._tapes.get(session_id)
        if tape is None:
            return None
        return tape.cut()

    def reset_if_settled(self, session_id: str, history_len: int) -> None:
        """Advance the tape base after a turn flushed to disk.

        Persisted history now covers everything recorded, so the tape can
        restart from the new item count — attaches to idle sessions replay
        compact synthesized history instead of the raw event stream, and tape
        memory stays bounded to the in-flight turn. Skipped when the tail
        shows a new turn already brewing (a user message or task start landed
        after the flush check).
        """
        tape = self._tapes.get(session_id)
        if tape is None:
            return
        last = tape.last_event()
        if isinstance(last, events.UserMessageEvent | events.TaskStartEvent):
            return
        tape.reset(history_len)

    def drop(self, session_id: str) -> None:
        self._tapes.pop(session_id, None)
