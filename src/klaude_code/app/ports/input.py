from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from klaude_code.protocol.message import UserInputPayload


class InputProviderABC(ABC):
    @abstractmethod
    async def start(self) -> None:
        pass

    @abstractmethod
    async def stop(self) -> None:
        pass

    @abstractmethod
    async def iter_inputs(self) -> AsyncIterator[UserInputPayload]:
        raise NotImplementedError
        yield UserInputPayload(text="")
