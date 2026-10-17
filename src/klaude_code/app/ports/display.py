from abc import ABC, abstractmethod

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
