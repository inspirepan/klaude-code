from collections.abc import Callable
from typing import TYPE_CHECKING, TypeVar

from klaude_code.protocol import llm_param

if TYPE_CHECKING:
    from klaude_code.llm.client import LLMClientABC

_T = TypeVar("_T", bound=type["LLMClientABC"])

# Track which protocols have been loaded
_loaded_protocols: set[llm_param.LLMClientProtocol] = set()
_REGISTRY: dict[llm_param.LLMClientProtocol, type["LLMClientABC"]] = {}


def _load_protocol(protocol: llm_param.LLMClientProtocol) -> None:
    """Load the module for a specific protocol on demand."""
    if protocol in _loaded_protocols:
        return
    _loaded_protocols.add(protocol)

    # Import only the needed module to trigger @register decorator
    if protocol == llm_param.LLMClientProtocol.ANTHROPIC:
        from . import anthropic as _
    elif protocol == llm_param.LLMClientProtocol.CODEX:
        from . import codex as _
    elif protocol == llm_param.LLMClientProtocol.OPENAI:
        from . import openai_compatible as _
    elif protocol == llm_param.LLMClientProtocol.OPENROUTER:
        from . import openrouter as _
    elif protocol == llm_param.LLMClientProtocol.RESPONSES:
        from . import responses as _  # noqa: F401


def register(name: llm_param.LLMClientProtocol) -> Callable[[_T], _T]:
    """Decorator to register an LLM client class for a protocol."""

    def _decorator(cls: _T) -> _T:
        _REGISTRY[name] = cls
        return cls

    return _decorator


def create_llm_client(config: llm_param.LLMConfigParameter) -> "LLMClientABC":
    _load_protocol(config.protocol)
    if config.protocol not in _REGISTRY:
        raise ValueError(f"Unknown LLMClient protocol: {config.protocol}")
    return _REGISTRY[config.protocol].create(config)
