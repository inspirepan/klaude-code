from datetime import datetime
from typing import override

from codex_mini.protocol.events import Event
from codex_mini.trace import log_debug
from codex_mini.ui.base.display_abc import DisplayABC


class DebugEventDisplay(DisplayABC):
    def __init__(
        self, wrapped_display: DisplayABC | None = None, write_to_file: bool = False, log_file: str = "debug.log"
    ):
        self.wrapped_display = wrapped_display
        self.write_to_file = write_to_file
        self.log_file = log_file

    @override
    async def consume_event(self, event: Event) -> None:
        message = f"🧩 ui [{event.__class__.__name__}] {event.model_dump_json()}"

        if self.write_to_file:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(f"[{timestamp}] {message}\n")
        else:
            log_debug(f"🧩 ui [{event.__class__.__name__}]", event.model_dump_json(), style="magenta")

        if self.wrapped_display:
            await self.wrapped_display.consume_event(event)

    async def start(self) -> None:
        if self.wrapped_display:
            await self.wrapped_display.start()

    async def stop(self) -> None:
        if self.wrapped_display:
            await self.wrapped_display.stop()
