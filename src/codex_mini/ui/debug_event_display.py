from typing import override

from codex_mini.protocol.events import Event
from codex_mini.trace import log_debug
from codex_mini.ui.display_abc import DisplayABC


class DebugEventDisplay(DisplayABC):
    @override
    async def consume_event(self, event: Event) -> None:
        log_debug(f"▶▶▶ ui [{event.__class__.__name__}]", event.model_dump_json(), style="magenta")

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass
