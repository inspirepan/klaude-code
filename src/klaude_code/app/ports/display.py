from abc import ABC, abstractmethod
from asyncio import Queue

from klaude_code.log import log
from klaude_code.protocol import events


class DisplayABC(ABC):
    @abstractmethod
    async def consume_envelope(self, envelope: events.EventEnvelope) -> None:
        pass

    @abstractmethod
    async def start(self) -> None:
        pass

    @abstractmethod
    async def stop(self) -> None:
        pass

    async def consume_event_loop(self, q: Queue[events.EventEnvelope]) -> None:
        await self.start()
        while True:
            envelope = await q.get()
            try:
                if isinstance(envelope.event, events.EndEvent):
                    await self.stop()
                    break
                await self.consume_envelope(envelope)
            except Exception as e:
                import traceback

                log(f"Error in consume_event_loop, {e.__class__.__name__}, {e}")
                log(traceback.format_exc())
            finally:
                q.task_done()
