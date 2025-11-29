import json
from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator
from typing import Callable, ParamSpec, TypeVar, cast

from klaude_code.protocol.llm_parameter import LLMCallParameter, LLMConfigParameter
from klaude_code.protocol.model import ConversationItem
from klaude_code.trace import DebugType, log_debug


class LLMClientABC(ABC):
    def __init__(self, config: LLMConfigParameter) -> None:
        self._config = config

    @classmethod
    @abstractmethod
    def create(cls, config: LLMConfigParameter) -> "LLMClientABC":
        pass

    @abstractmethod
    async def call(self, param: LLMCallParameter) -> AsyncGenerator[ConversationItem, None]:
        raise NotImplementedError
        yield cast(ConversationItem, None)  # pyright: ignore[reportUnreachable]

    def get_llm_config(self) -> LLMConfigParameter:
        return self._config

    @property
    def model_name(self) -> str:
        return self._config.model or ""


P = ParamSpec("P")
R = TypeVar("R")


def call_with_logged_payload(func: Callable[P, R], *args: P.args, **kwargs: P.kwargs) -> R:
    """Call an SDK function while logging the JSON payload.

    The function reuses the original callable's type signature via ParamSpec
    so static type checkers can validate arguments at the call site.
    """

    payload = {k: v for k, v in kwargs.items() if v is not None}
    log_debug(
        json.dumps(payload, ensure_ascii=False, default=str),
        style="yellow",
        debug_type=DebugType.LLM_PAYLOAD,
    )
    return func(*args, **kwargs)
