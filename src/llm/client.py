from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator
from typing import cast

from src.config import Config
from src.protocal.llm_parameter import LLMParameter
from src.protocal.model import ResponseItem


class LLMClient(ABC):
    @classmethod
    @abstractmethod
    def create(cls, config: Config) -> "LLMClient":
        pass

    @abstractmethod
    async def Call(self, param: LLMParameter) -> AsyncGenerator[ResponseItem, None]:
        """
        [ReasoningItemDelta]
        [AssistantMessageDelta]
        [ReasoningItem]
        [AssistantMessage]
        [ToolCallItem]
        """
        raise NotImplementedError
        yield cast(ResponseItem, None)  # pyright: ignore[reportUnreachable]
