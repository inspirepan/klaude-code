from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from pathlib import Path
from typing import Any, TypeVar

from klaude_code.core.control.event_bus import EnvelopeBus, EventBus
from klaude_code.core.control.event_relay import EventRelayPublisher, EventRelayServer, event_relay_socket_path
from klaude_code.protocol import events

T = TypeVar("T")


def arun[T](coro: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(coro)


def test_event_relay_round_trips_ephemeral_event(tmp_path: Path) -> None:
    async def _test() -> None:
        socket_path = event_relay_socket_path(home_dir=tmp_path)
        relay_bus = EnvelopeBus()
        relay_server = EventRelayServer(socket_path=socket_path, envelope_bus=relay_bus)
        relay_publisher = EventRelayPublisher(socket_path=socket_path)
        runtime_bus = EventBus(publish_hook=relay_publisher.publish)
        subscription = relay_bus.subscribe("s1")
        iterator = subscription.__aiter__()

        await relay_server.start()
        try:
            await runtime_bus.publish(events.AssistantTextDeltaEvent(session_id="s1", content="hello"))
            envelope = await asyncio.wait_for(anext(iterator), timeout=1.0)
        finally:
            await relay_publisher.aclose()
            await relay_server.aclose()

        assert envelope.event_seq == 1
        assert envelope.event_type == "assistant.text.delta"
        assert envelope.durability == "ephemeral"
        assert isinstance(envelope.event, events.AssistantTextDeltaEvent)
        assert envelope.event.content == "hello"

    arun(_test())
