import json
from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator
from typing import Callable, ParamSpec, TypeVar, cast

from klaude_code.protocol import llm_param, model
from klaude_code.trace import DebugType, log_debug


class LLMClientABC(ABC):
    def __init__(self, config: llm_param.LLMConfigParameter) -> None:
        self._config = config

    @classmethod
    @abstractmethod
    def create(cls, config: llm_param.LLMConfigParameter) -> "LLMClientABC":
        pass

    @abstractmethod
    async def call(self, param: llm_param.LLMCallParameter) -> AsyncGenerator[model.ConversationItem, None]:
        raise NotImplementedError
        yield cast(model.ConversationItem, None)

    def get_llm_config(self) -> llm_param.LLMConfigParameter:
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
