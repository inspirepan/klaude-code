from typing import override

from klaude_code.const import DEFAULT_DEBUG_LOG_FILE
from klaude_code.protocol.events import Event
from klaude_code.trace import DebugType, log_debug
from klaude_code.ui.base.display_abc import DisplayABC


class DebugEventDisplay(DisplayABC):
    def __init__(self, wrapped_display: DisplayABC | None = None, log_file: str = DEFAULT_DEBUG_LOG_FILE):
        self.wrapped_display = wrapped_display
        self.log_file = log_file

    @override
    async def consume_event(self, event: Event) -> None:
        log_debug(
            f"[{event.__class__.__name__}]",
            event.model_dump_json(exclude_none=True),
            style="magenta",
            debug_type=DebugType.UI_EVENT,
        )

        if self.wrapped_display:
            await self.wrapped_display.consume_event(event)

    async def start(self) -> None:
        if self.wrapped_display:
            await self.wrapped_display.start()

    async def stop(self) -> None:
        if self.wrapped_display:
            await self.wrapped_display.stop()
