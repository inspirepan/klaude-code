from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from contextvars import ContextVar
from dataclasses import dataclass
from uuid import uuid4

from klaude_code.protocol import events


class _DisconnectSentinel:
    pass


_DISCONNECT_SENTINEL = _DisconnectSentinel()

_CURRENT_OPERATION_ID: ContextVar[str | None] = ContextVar("klaude_event_operation_id", default=None)
_CURRENT_TASK_ID: ContextVar[str | None] = ContextVar("klaude_event_task_id", default=None)
_CURRENT_CAUSATION_ID: ContextVar[str | None] = ContextVar("klaude_event_causation_id", default=None)


@contextlib.contextmanager
def event_publish_context(
    *,
    operation_id: str | None = None,
    task_id: str | None = None,
    causation_id: str | None = None,
):
    operation_token = _CURRENT_OPERATION_ID.set(
        operation_id if operation_id is not None else _CURRENT_OPERATION_ID.get()
    )
    task_token = _CURRENT_TASK_ID.set(task_id if task_id is not None else _CURRENT_TASK_ID.get())
    causation_token = _CURRENT_CAUSATION_ID.set(
        causation_id if causation_id is not None else _CURRENT_CAUSATION_ID.get()
    )
    try:
        yield
    finally:
        _CURRENT_CAUSATION_ID.reset(causation_token)
        _CURRENT_TASK_ID.reset(task_token)
        _CURRENT_OPERATION_ID.reset(operation_token)


@dataclass(frozen=True)
class _Subscriber:
    subscriber_id: str
    session_id: str | None
    queue: asyncio.Queue[events.EventEnvelope | _DisconnectSentinel]


class EventSubscription:
    def __init__(
        self,
        *,
        bus: EventBus,
        subscriber_id: str,
        queue: asyncio.Queue[events.EventEnvelope | _DisconnectSentinel],
    ) -> None:
        self._bus = bus
        self._subscriber_id = subscriber_id
        self._queue = queue

    def __aiter__(self) -> AsyncIterator[events.EventEnvelope]:
        return self._iter_envelopes()

    async def _iter_envelopes(self) -> AsyncIterator[events.EventEnvelope]:
        try:
            while True:
                item = await self._queue.get()
                try:
                    if isinstance(item, _DisconnectSentinel):
                        return
                    yield item
                finally:
                    self._queue.task_done()
        finally:
            await self._bus.detach(self._subscriber_id)

    async def iter_events(self) -> AsyncIterator[events.Event]:
        async for envelope in self:
            yield envelope.event

    async def wait_for_drain(self) -> None:
        await self._queue.join()


class EventBus:
    def __init__(self, *, subscriber_queue_maxsize: int = 1024) -> None:
        self._subscriber_queue_maxsize = subscriber_queue_maxsize
        self._subscribers: dict[str, _Subscriber] = {}
        self._session_event_seq: dict[str, int] = {}

    async def publish(
        self,
        event: events.Event,
        *,
        operation_id: str | None = None,
        task_id: str | None = None,
        causation_id: str | None = None,
    ) -> None:
        resolved_operation_id = operation_id if operation_id is not None else _CURRENT_OPERATION_ID.get()
        resolved_task_id = task_id if task_id is not None else _CURRENT_TASK_ID.get()
        resolved_causation_id = causation_id if causation_id is not None else _CURRENT_CAUSATION_ID.get()
        event_type = events.event_type_name(event)
        envelope = events.EventEnvelope(
            event_id=uuid4().hex,
            event_seq=self._next_event_seq(event.session_id),
            session_id=event.session_id,
            operation_id=resolved_operation_id,
            task_id=resolved_task_id,
            causation_id=resolved_causation_id,
            event_type=event_type,
            durability=events.event_durability(event_type),
            timestamp=event.timestamp,
            event=event,
        )

        overflowed_ids: list[str] = []
        for subscriber_id, subscriber in list(self._subscribers.items()):
            if subscriber.session_id is not None and subscriber.session_id != envelope.session_id:
                continue
            try:
                subscriber.queue.put_nowait(envelope)
            except asyncio.QueueFull:
                overflowed_ids.append(subscriber_id)

        for subscriber_id in overflowed_ids:
            self._disconnect_subscriber(subscriber_id, notify=True)

    def subscribe(self, session_id: str | None) -> EventSubscription:
        subscriber_id = uuid4().hex
        queue: asyncio.Queue[events.EventEnvelope | _DisconnectSentinel] = asyncio.Queue(
            maxsize=self._subscriber_queue_maxsize
        )
        self._subscribers[subscriber_id] = _Subscriber(
            subscriber_id=subscriber_id,
            session_id=session_id,
            queue=queue,
        )
        return EventSubscription(bus=self, subscriber_id=subscriber_id, queue=queue)

    async def unsubscribe(self, subscriber_id: str) -> None:
        self._disconnect_subscriber(subscriber_id, notify=True)

    async def detach(self, subscriber_id: str) -> None:
        self._disconnect_subscriber(subscriber_id, notify=False)

    def _disconnect_subscriber(self, subscriber_id: str, *, notify: bool) -> None:
        subscriber = self._subscribers.pop(subscriber_id, None)
        if subscriber is None:
            return

        if not notify:
            return

        while True:
            try:
                _ = subscriber.queue.get_nowait()
                subscriber.queue.task_done()
            except asyncio.QueueEmpty:
                break

        subscriber.queue.put_nowait(_DISCONNECT_SENTINEL)

    def _next_event_seq(self, session_id: str) -> int:
        next_seq = self._session_event_seq.get(session_id, 0) + 1
        self._session_event_seq[session_id] = next_seq
        return next_seq
