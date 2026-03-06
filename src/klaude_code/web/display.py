from __future__ import annotations

from klaude_code.app.ports import DisplayABC
from klaude_code.protocol import events


class WebDisplay(DisplayABC):
    """No-op display adapter for web mode.

    Web mode delivers events to clients over WebSocket, so server-side rendering
    is intentionally disabled.
    """

    async def consume_envelope(self, envelope: events.EventEnvelope) -> None:
        del envelope

    async def start(self) -> None:
        return

    async def stop(self) -> None:
        return
