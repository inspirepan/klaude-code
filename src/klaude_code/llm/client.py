from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator
from typing import ParamSpec, TypeVar, cast

from klaude_code.protocol import llm_param, model


class LLMClientABC(ABC):
    def __init__(self, config: llm_param.LLMConfigParameter) -> None:
        self._config = config

    @classmethod
    @abstractmethod
    def create(cls, config: llm_param.LLMConfigParameter) -> "LLMClientABC":
        pass

    @abstractmethod
    async def call(self, param: llm_param.LLMCallParameter) -> AsyncGenerator[model.ConversationItem]:
        raise NotImplementedError
        yield cast(model.ConversationItem, None)

    def get_llm_config(self) -> llm_param.LLMConfigParameter:
        return self._config

    @property
    def model_name(self) -> str:
        return self._config.model or ""

    @property
    def protocol(self) -> llm_param.LLMClientProtocol:
        return self._config.protocol


P = ParamSpec("P")
R = TypeVar("R")
