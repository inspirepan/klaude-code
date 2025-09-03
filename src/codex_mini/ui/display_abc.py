from abc import ABC, abstractmethod
from asyncio import Queue

from codex_mini.protocol import EndEvent, Event


class Display(ABC):
    @abstractmethod
    async def consume_event(self, event: Event) -> None:
        pass

    @abstractmethod
    async def start(self) -> None:
        pass

    @abstractmethod
    async def stop(self) -> None:
        pass

    async def consume_event_loop(self, q: Queue[Event]) -> None:
        await self.start()
        while True:
            event = await q.get()
            try:
                if isinstance(event, EndEvent):
                    await self.stop()
                    break
                await self.consume_event(event)
            finally:
                q.task_done()
