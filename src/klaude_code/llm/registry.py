from typing import TYPE_CHECKING, Callable, TypeVar

from klaude_code.protocol import llm_param

if TYPE_CHECKING:
    from klaude_code.llm.client import LLMClientABC

_REGISTRY: dict[llm_param.LLMClientProtocol, type["LLMClientABC"]] = {}

T = TypeVar("T", bound="LLMClientABC")

# Lazy loading flag
_clients_loaded = False


def register(name: llm_param.LLMClientProtocol) -> Callable[[type[T]], type[T]]:
    def _decorator(cls: type[T]) -> type[T]:
        _REGISTRY[name] = cls
        return cls

    return _decorator


def ensure_clients_loaded() -> None:
    """Ensure all LLM clients are loaded (lazy initialization)."""
    global _clients_loaded
    if _clients_loaded:
        return
    _clients_loaded = True

    # Import client modules to trigger @register decorators
    from . import anthropic as _anthropic  # noqa: F401
    from . import codex as _codex  # noqa: F401
    from . import openai_compatible as _openai_compatible  # noqa: F401
    from . import openrouter as _openrouter  # noqa: F401
    from . import responses as _responses  # noqa: F401

    # Suppress unused variable warnings
    _ = (_anthropic, _codex, _openai_compatible, _openrouter, _responses)


def create_llm_client(config: llm_param.LLMConfigParameter) -> "LLMClientABC":
    ensure_clients_loaded()
    if config.protocol not in _REGISTRY:
        raise ValueError(f"Unknown LLMClient protocol: {config.protocol}")
    return _REGISTRY[config.protocol].create(config)
