from typing import override
from rich.console import Console

from codex_mini.protocol.events import Event
from codex_mini.ui.display_abc import DisplayABC


class DebugEventDisplay(DisplayABC):
    def __init__(self):
        self.console: Console = Console()

    @override
    async def consume_event(self, event: Event) -> None:
        self.console.print(f"▶▶▶ [{event.__class__.__name__}]", event.model_dump_json(indent=2))

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass
