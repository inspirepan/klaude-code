from __future__ import annotations

from typing import override

from codex_mini.protocol import events
from codex_mini.ui.display_abc import DisplayABC
from codex_mini.ui.repl_event_handler import DisplayEventHandler
from codex_mini.ui.repl_renderer import REPLRenderer


class REPLDisplay(DisplayABC):
    """Coordinate renderer and event handler for the REPL UI."""

    def __init__(self, theme: str | None = None):
        self.renderer = REPLRenderer(theme)
        self.event_handler = DisplayEventHandler(self.renderer)

    @override
    async def consume_event(self, event: events.Event) -> None:
        await self.event_handler.consume_event(event)

    @override
    async def start(self) -> None:
        pass

    @override
    async def stop(self) -> None:
        await self.event_handler.stop()
