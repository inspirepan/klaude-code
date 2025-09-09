from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator
from typing import cast

from codex_mini.protocol.llm_parameter import LLMCallParameter, LLMConfigParameter
from codex_mini.protocol.model import ConversationItem


class LLMClientABC(ABC):
    def __init__(self, config: LLMConfigParameter) -> None:
        self.debug_mode: bool = False
        self._config = config

    @classmethod
    @abstractmethod
    def create(cls, config: LLMConfigParameter) -> "LLMClientABC":
        pass

    @abstractmethod
    async def call(self, param: LLMCallParameter) -> AsyncGenerator[ConversationItem, None]:
        raise NotImplementedError
        yield cast(ConversationItem, None)  # pyright: ignore[reportUnreachable]

    def enable_debug_mode(self) -> None:
        self.debug_mode = True

    def disable_debug_mode(self) -> None:
        self.debug_mode = False

    def is_debug_mode(self) -> bool:
        return self.debug_mode

    def get_llm_config(self) -> LLMConfigParameter:
        return self._config

    @abstractmethod
    def model_name(self) -> str:
        raise NotImplementedError
