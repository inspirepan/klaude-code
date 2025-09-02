from typing import Callable, TypeVar

from src.config import LLMConfig
from src.llm.client import LLMClient

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
    if config.protocal not in _REGISTRY:
        raise ValueError(f"Unknown LLMClient: {config.protocal}")
    return _REGISTRY[config.protocal].create(config.llm_parameter)
