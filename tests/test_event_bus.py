from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Coroutine
from typing import Any, TypeVar

from klaude_code.core.control.event_bus import EventBus, EventSubscription, event_publish_context
from klaude_code.protocol import events

T = TypeVar("T")


def arun[T](coro: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(coro)


def _event(session_id: str, content: str) -> events.UserMessageEvent:
    return events.UserMessageEvent(session_id=session_id, content=content)


def test_event_bus_disconnects_slow_subscriber_on_overflow() -> None:
    async def _test() -> None:
        bus = EventBus(subscriber_queue_maxsize=1)
        subscription = bus.subscribe(None)

        await bus.publish(_event("s1", "first"))
        await bus.publish(_event("s1", "second"))

        # After overflow, already-queued events are preserved and delivered
        # before the disconnect sentinel.  "first" was queued successfully;
        # "second" triggered the overflow and was dropped.
        collected: list[events.Event] = []
        async for evt in subscription.iter_events():
            collected.append(evt)

        assert len(collected) == 1
        assert isinstance(collected[0], events.UserMessageEvent)
        assert collected[0].content == "first"

    arun(_test())


def test_event_bus_filters_by_session() -> None:
    async def _test() -> None:
        bus = EventBus()
        all_events = bus.subscribe(None)
        s1_events = bus.subscribe("s1")

        await bus.publish(_event("s1", "hello s1"))
        await bus.publish(_event("s2", "hello s2"))

        all_collected: list[events.EventEnvelope] = []
        async for evt in all_events:
            all_collected.append(evt)
            if len(all_collected) == 2:
                break

        s1_collected: list[events.EventEnvelope] = []
        async for evt in s1_events:
            s1_collected.append(evt)
            if len(s1_collected) == 1:
                break

        assert [evt.session_id for evt in all_collected] == ["s1", "s2"]
        all_events_payload = [evt.event for evt in all_collected]
        assert isinstance(all_events_payload[0], events.UserMessageEvent)
        assert isinstance(all_events_payload[1], events.UserMessageEvent)
        assert all_events_payload[0].content == "hello s1"
        assert all_events_payload[1].content == "hello s2"
        assert [evt.session_id for evt in s1_collected] == ["s1"]
        assert isinstance(s1_collected[0].event, events.UserMessageEvent)
        assert s1_collected[0].event.content == "hello s1"

    arun(_test())


def test_event_bus_bridge_wait_for_drain() -> None:
    async def _test() -> None:
        bus = EventBus()
        queue: asyncio.Queue[events.Event] = asyncio.Queue()
        subscription = bus.subscribe(None)

        async def _bridge(sub: EventSubscription, out_queue: asyncio.Queue[events.Event]) -> None:
            async for evt in sub.iter_events():
                await out_queue.put(evt)

        bridge_task = asyncio.create_task(_bridge(subscription, queue))

        await bus.publish(_event("s1", "a"))
        await bus.publish(_event("s1", "b"))

        await subscription.wait_for_drain()
        assert queue.qsize() == 2

        first = await queue.get()
        second = await queue.get()
        queue.task_done()
        queue.task_done()

        assert isinstance(first, events.UserMessageEvent)
        assert isinstance(second, events.UserMessageEvent)
        assert first.content == "a"
        assert second.content == "b"

        bridge_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await bridge_task

    arun(_test())


def test_event_bus_envelope_has_seq_and_event_type() -> None:
    async def _test() -> None:
        bus = EventBus()
        sub = bus.subscribe("s1")

        await bus.publish(events.UserMessageEvent(session_id="s1", content="hello"))
        await bus.publish(
            events.OperationRejectedEvent(
                session_id="s1",
                operation_id="op1",
                operation_type="run_agent",
                reason="session_busy",
                active_task_id="task1",
            )
        )

        iterator = sub.__aiter__()
        first = await anext(iterator)
        second = await anext(iterator)

        assert first.event_seq == 1
        assert second.event_seq == 2
        assert first.event_type == "user.message"
        assert second.event_type == "operation.rejected"
        assert first.durability == "durable"
        assert second.durability == "ephemeral"

    arun(_test())


def test_event_bus_envelope_carries_operation_task_and_causation_metadata() -> None:
    async def _test() -> None:
        bus = EventBus()
        sub = bus.subscribe("s1")

        with event_publish_context(operation_id="op-ctx", task_id="task-ctx"):
            await bus.publish(events.UserMessageEvent(session_id="s1", content="from-context"))

        await bus.publish(
            events.UserMessageEvent(session_id="s1", content="from-explicit"),
            operation_id="op-explicit",
            task_id="task-explicit",
            causation_id="req-1",
        )

        iterator = sub.__aiter__()
        first = await anext(iterator)
        second = await anext(iterator)

        assert first.operation_id == "op-ctx"
        assert first.task_id == "task-ctx"
        assert first.causation_id is None

        assert second.operation_id == "op-explicit"
        assert second.task_id == "task-explicit"
        assert second.causation_id == "req-1"

    arun(_test())
