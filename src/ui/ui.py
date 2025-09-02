from abc import ABC, abstractmethod
from asyncio import Queue

from src.protocal import Event, EndEvent


class Display(ABC):
    def __init__(self):
        pass

    @abstractmethod
    async def consume_event(self, event: Event) -> None:
        pass

    async def consume_event_loop(self, q: Queue[Event]) -> None:
        while True:
            event = await q.get()
            try:
                if isinstance(event, EndEvent):
                    break
                await self.consume_event(event)
            finally:
                q.task_done()
