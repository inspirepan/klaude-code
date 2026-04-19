from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass
from pathlib import Path

from klaude_code.control.event_bus import EnvelopeBus, EventBus
from klaude_code.control.event_relay import EventRelayServer, event_relay_socket_path
from klaude_code.log import DebugType, log_debug


@dataclass
class WebLiveEvents:
    stream: EnvelopeBus
    relay_server: EventRelayServer | None
    forward_task: asyncio.Task[None]
    relay_error: str | None = None

    async def aclose(self) -> None:
        self.forward_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self.forward_task
        if self.relay_server is not None:
            await self.relay_server.aclose()

async def start_web_live_events(event_bus: EventBus, *, home_dir: Path) -> WebLiveEvents:
    stream = EnvelopeBus()
    subscription = event_bus.subscribe(None)

    async def _forward_local_events() -> None:
        async for envelope in subscription:
            await stream.publish_envelope(envelope)

    forward_task = asyncio.create_task(_forward_local_events())
    relay_server: EventRelayServer | None = None
    relay_error: str | None = None
    try:
        relay_server = EventRelayServer(socket_path=event_relay_socket_path(home_dir=home_dir), envelope_bus=stream)
        await relay_server.start()
    except RuntimeError as exc:
        relay_error = str(exc)
        log_debug(relay_error, debug_type=DebugType.EVENT_BUS)

    return WebLiveEvents(
        stream=stream,
        relay_server=relay_server,
        forward_task=forward_task,
        relay_error=relay_error,
    )
