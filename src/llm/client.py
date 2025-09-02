from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator
from typing import cast

from src.protocal import LLMCallParameter, LLMConfigParameter, ResponseItem


class LLMClient(ABC):
    @classmethod
    @abstractmethod
    def create(cls, config: LLMConfigParameter) -> "LLMClient":
        pass

    @abstractmethod
    async def Call(self, param: LLMCallParameter) -> AsyncGenerator[ResponseItem, None]:
        raise NotImplementedError
        yield cast(ResponseItem, None)  # pyright: ignore[reportUnreachable]
