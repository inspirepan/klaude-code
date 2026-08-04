from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass

from klaude_code.control.event_bus import EnvelopeBus, EventBus


@dataclass
class ServerLiveEvents:
    """Envelope stream fanned out to WS clients, fed from the origin bus."""

    stream: EnvelopeBus
    forward_task: asyncio.Task[None]

    async def aclose(self) -> None:
        self.forward_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self.forward_task


def start_server_live_events(event_bus: EventBus) -> ServerLiveEvents:
    stream = EnvelopeBus()
    subscription = event_bus.subscribe(None)

    async def _forward_local_events() -> None:
        async for envelope in subscription:
            await stream.publish_envelope(envelope)

    return ServerLiveEvents(stream=stream, forward_task=asyncio.create_task(_forward_local_events()))
