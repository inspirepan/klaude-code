from __future__ import annotations

from typing import override

from klaude_code.protocol import events
from klaude_code.ui.base.display_abc import DisplayABC
from klaude_code.ui.base.terminal_notifier import TerminalNotifier
from klaude_code.ui.repl.event_handler import DisplayEventHandler
from klaude_code.ui.repl.renderer import REPLRenderer


class REPLDisplay(DisplayABC):
    """Coordinate renderer and event handler for the REPL UI."""

    def __init__(self, theme: str | None = None, notifier: TerminalNotifier | None = None):
        self.renderer = REPLRenderer(theme)
        self.notifier = notifier or TerminalNotifier()
        self.event_handler = DisplayEventHandler(self.renderer, notifier=self.notifier)

    @override
    async def consume_event(self, event: events.Event) -> None:
        await self.event_handler.consume_event(event)

    @override
    async def start(self) -> None:
        pass

    @override
    async def stop(self) -> None:
        await self.event_handler.stop()
        # Ensure any active spinner is stopped so Rich restores the cursor.
        try:
            self.renderer.spinner.stop()
        except Exception:
            # Spinner may already be stopped or not started; ignore.
            pass
