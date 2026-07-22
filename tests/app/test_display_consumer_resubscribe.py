"""The bus disconnects a subscriber whose queue overflows; the display
consumer must resubscribe instead of going permanently silent."""

from __future__ import annotations

import asyncio

from klaude_code.app.runtime import SubscriptionHolder, _consume_display_from_subscription
from klaude_code.control.event_bus import EventBus
from klaude_code.protocol import events


class _RecordingDisplay:
    def __init__(self) -> None:
        self.consumed: list[events.Event] = []
        self.stopped = False

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        self.stopped = True

    async def consume_envelope(self, envelope: events.EventEnvelope) -> None:
        self.consumed.append(envelope.event)


def _user_message(session_id: str = "s1") -> events.UserMessageEvent:
    return events.UserMessageEvent(session_id=session_id, content="hello")


def test_display_consumer_resubscribes_after_overflow() -> None:
    async def _run() -> None:
        bus = EventBus(subscriber_queue_maxsize=4)
        holder = SubscriptionHolder(subscription=bus.subscribe(None))
        display = _RecordingDisplay()

        consumer = asyncio.create_task(
            _consume_display_from_subscription(bus, holder, display)  # pyright: ignore[reportArgumentType]
        )
        # Overflow before the consumer drains: fill to maxsize, then one more
        # publish disconnects the subscriber.
        for _ in range(5):
            await bus.publish(_user_message())

        # Let the consumer drain the backlog, hit the sentinel, resubscribe.
        await asyncio.sleep(0.05)
        assert not consumer.done()

        # Events published after the overflow must reach the fresh subscription.
        await bus.publish(_user_message("s2"))
        await asyncio.sleep(0.05)
        assert any(event.session_id == "s2" for event in display.consumed)

        # EndEvent still terminates the loop cleanly.
        await bus.publish(events.EndEvent(session_id="s2"))
        await asyncio.wait_for(consumer, timeout=1)
        assert display.stopped

    asyncio.run(_run())


def test_wait_for_display_idle_targets_live_subscription() -> None:
    async def _run() -> None:
        bus = EventBus(subscriber_queue_maxsize=4)
        holder = SubscriptionHolder(subscription=bus.subscribe(None))
        stale = holder.subscription
        holder.subscription = bus.subscribe(None)

        # Draining the holder must not wait on the stale subscription's queue.
        stale._queue.put_nowait(  # pyright: ignore[reportPrivateUsage]
            events.EventEnvelope(
                event_id="x",
                event_seq=1,
                session_id="s1",
                operation_id=None,
                task_id=None,
                causation_id=None,
                event_type="user.message",
                durability=events.event_durability("user.message"),
                timestamp=0.0,
                event=_user_message(),
            )
        )
        await asyncio.wait_for(holder.subscription.wait_for_drain(), timeout=1)

    asyncio.run(_run())
