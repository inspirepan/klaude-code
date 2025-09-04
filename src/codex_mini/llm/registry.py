from typing import Callable, TypeVar

from codex_mini.llm.client import LLMClientABC
from codex_mini.protocol.llm_parameter import LLMClientProtocol, LLMConfigParameter

_REGISTRY: dict[LLMClientProtocol, type[LLMClientABC]] = {}

T = TypeVar("T", bound=LLMClientABC)


def register(name: LLMClientProtocol) -> Callable[[type[T]], type[T]]:
    def _decorator(cls: type[T]) -> type[T]:
        _REGISTRY[name] = cls
        return cls

    return _decorator


def create_llm_client(config: LLMConfigParameter) -> LLMClientABC:
    if config.protocol not in _REGISTRY:
        raise ValueError(f"Unknown LLMClient protocol: {config.protocol}")
    return _REGISTRY[config.protocol].create(config)
