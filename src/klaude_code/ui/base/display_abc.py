from abc import ABC, abstractmethod
from asyncio import Queue

from klaude_code.protocol import events
from klaude_code.trace import log


class DisplayABC(ABC):
    @abstractmethod
    async def consume_event(self, event: events.Event) -> None:
        pass

    @abstractmethod
    async def start(self) -> None:
        pass

    @abstractmethod
    async def stop(self) -> None:
        pass

    async def consume_event_loop(self, q: Queue[events.Event]) -> None:
        await self.start()
        while True:
            event = await q.get()
            try:
                if isinstance(event, events.EndEvent):
                    await self.stop()
                    break
                await self.consume_event(event)
            except Exception as e:
                import traceback

                log(
                    f"Error in consume_event_loop, {e.__class__.__name__}, {e}",
                    style="red",
                )
                log(traceback.format_exc(), style="red")
            finally:
                q.task_done()
