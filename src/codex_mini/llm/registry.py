from typing import Callable, TypeVar

from codex_mini.config import LLMConfig
from codex_mini.llm.client import LLMClient

_REGISTRY: dict[str, type[LLMClient]] = {}

T = TypeVar("T", bound=LLMClient)


def register(name: str) -> Callable[[type[T]], type[T]]:
    def _decorator(cls: type[T]) -> type[T]:
        _REGISTRY[name] = cls
        return cls

    return _decorator


def clients() -> list[str]:
    return list(_REGISTRY.keys())


def create_llm_client(config: LLMConfig) -> LLMClient:
    if config.protocol not in _REGISTRY:
        raise ValueError(f"Unknown LLMClient: {config.protocol}")
    return _REGISTRY[config.protocol].create(config.llm_parameter)
