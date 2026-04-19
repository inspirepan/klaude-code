from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator
from typing import ParamSpec, TypeVar

from klaude_code.protocol import llm_param, message


class LLMStreamABC(ABC):
    """Abstract base class for LLM streaming response with state access.

    Provides both async iteration over stream items and access to accumulated
    message state for cancellation scenarios.
    """

    @abstractmethod
    def __aiter__(self) -> AsyncGenerator[message.LLMStreamItem]:
        """Iterate over stream items."""
        ...

    @abstractmethod
    def get_partial_message(self) -> message.AssistantMessage | None:
        """Get accumulated message for cancel scenarios.

        Returns the message constructed from accumulated parts so far,
        including thinking and assistant text. Returns None if no content
        has been accumulated yet.

        """
        ...


class LLMClientABC(ABC):
    def __init__(self, config: llm_param.LLMConfigParameter) -> None:
        self._config = config

    @classmethod
    @abstractmethod
    def create(cls, config: llm_param.LLMConfigParameter) -> "LLMClientABC":
        pass

    @abstractmethod
    async def call(self, param: llm_param.LLMCallParameter) -> LLMStreamABC:
        """Start an LLM call and return a stream object.

        The returned stream can be iterated to receive stream items,
        and provides get_partial_message() for cancellation scenarios.
        """
        raise NotImplementedError

    def get_llm_config(self) -> llm_param.LLMConfigParameter:
        return self._config

    @property
    def model_name(self) -> str:
        return self._config.model_id or ""

    @property
    def protocol(self) -> llm_param.LLMClientProtocol:
        return self._config.protocol


P = ParamSpec("P")
R = TypeVar("R")
