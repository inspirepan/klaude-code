from typing import Callable, TypeVar

from klaude_code.llm.client import LLMClientABC
from klaude_code.protocol import llm_param

_REGISTRY: dict[llm_param.LLMClientProtocol, type[LLMClientABC]] = {}

T = TypeVar("T", bound=LLMClientABC)


def register(name: llm_param.LLMClientProtocol) -> Callable[[type[T]], type[T]]:
    def _decorator(cls: type[T]) -> type[T]:
        _REGISTRY[name] = cls
        return cls

    return _decorator


def create_llm_client(config: llm_param.LLMConfigParameter) -> LLMClientABC:
    if config.protocol not in _REGISTRY:
        raise ValueError(f"Unknown LLMClient protocol: {config.protocol}")
    return _REGISTRY[config.protocol].create(config)
