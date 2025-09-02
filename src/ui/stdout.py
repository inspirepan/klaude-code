from typing import override

from rich.console import Console

from src.protocal import Event
from src.ui.ui import Display


class StdoutDisplay(Display):
    def __init__(self):
        self.console: Console = Console()

    @override
    async def consume_event(self, event: Event) -> None:
        self.console.print("[Event] ", event.__class__.__name__, event)
