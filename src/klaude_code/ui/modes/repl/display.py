from __future__ import annotations

import contextlib
from typing import override

from klaude_code.protocol import events
from klaude_code.ui.core.display import DisplayABC
from klaude_code.ui.modes.repl.event_handler import DisplayEventHandler
from klaude_code.ui.modes.repl.renderer import REPLRenderer
from klaude_code.ui.terminal.notifier import TerminalNotifier


class REPLDisplay(DisplayABC):
    """
    Interactive terminal display using Rich for rendering.

    REPLDisplay provides a full-featured terminal UI with:
    - Rich markdown rendering for assistant messages
    - Syntax-highlighted code blocks and diffs
    - Animated spinners for in-progress operations
    - Tool call and result visualization
    - OSC94 progress bar integration (for supported terminals)
    - Desktop notifications on task completion

    This is the primary display mode for interactive klaude-code sessions.
    For non-interactive use, see ExecDisplay. For debugging, wrap with
    DebugEventDisplay.

    Lifecycle:
        1. start(): No-op (initialization happens in __init__)
        2. consume_event(): Delegates to DisplayEventHandler for event processing
        3. stop(): Stops the event handler and ensures spinner is cleaned up

    Attributes:
        renderer: The REPLRenderer instance for terminal output
        notifier: TerminalNotifier for desktop notifications
        event_handler: DisplayEventHandler that processes events
    """

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
        # Spinner may already be stopped or not started; ignore.
        with contextlib.suppress(Exception):
            self.renderer.spinner_stop()
        with contextlib.suppress(Exception):
            self.renderer.stop_bottom_live()
