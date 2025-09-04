from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator
from typing import cast

from codex_mini.protocol.llm_parameter import LLMCallParameter, LLMConfigParameter
from codex_mini.protocol.model import ConversationItem


class LLMClientABC(ABC):
    @classmethod
    @abstractmethod
    def create(cls, config: LLMConfigParameter) -> "LLMClientABC":
        pass

    @abstractmethod
    async def Call(self, param: LLMCallParameter) -> AsyncGenerator[ConversationItem, None]:
        raise NotImplementedError
        yield cast(ConversationItem, None)  # pyright: ignore[reportUnreachable]
