from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Coroutine
from typing import Any, TypeVar

from klaude_code.core.event_bus import EventBus, EventSubscription
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

        collected: list[events.Event] = []
        async for evt in subscription:
            collected.append(evt)

        assert collected == []

    arun(_test())


def test_event_bus_filters_by_session() -> None:
    async def _test() -> None:
        bus = EventBus()
        all_events = bus.subscribe(None)
        s1_events = bus.subscribe("s1")

        await bus.publish(_event("s1", "hello s1"))
        await bus.publish(_event("s2", "hello s2"))

        all_collected: list[events.Event] = []
        async for evt in all_events:
            all_collected.append(evt)
            if len(all_collected) == 2:
                break

        s1_collected: list[events.Event] = []
        async for evt in s1_events:
            s1_collected.append(evt)
            if len(s1_collected) == 1:
                break

        assert [evt.session_id for evt in all_collected] == ["s1", "s2"]
        assert [evt.session_id for evt in s1_collected] == ["s1"]

    arun(_test())


def test_event_bus_bridge_wait_for_drain() -> None:
    async def _test() -> None:
        bus = EventBus()
        queue: asyncio.Queue[events.Event] = asyncio.Queue()
        subscription = bus.subscribe(None)

        async def _bridge(sub: EventSubscription, out_queue: asyncio.Queue[events.Event]) -> None:
            async for evt in sub:
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
