import importlib
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
        importlib.import_module("klaude_code.llm.anthropic")
    elif protocol == llm_param.LLMClientProtocol.BEDROCK:
        importlib.import_module("klaude_code.llm.bedrock")
    elif protocol == llm_param.LLMClientProtocol.CODEX:
        importlib.import_module("klaude_code.llm.codex")
    elif protocol == llm_param.LLMClientProtocol.OPENAI:
        importlib.import_module("klaude_code.llm.openai_compatible")
    elif protocol == llm_param.LLMClientProtocol.OPENROUTER:
        importlib.import_module("klaude_code.llm.openrouter")
    elif protocol == llm_param.LLMClientProtocol.RESPONSES:
        importlib.import_module("klaude_code.llm.responses")
    elif protocol == llm_param.LLMClientProtocol.GOOGLE:
        importlib.import_module("klaude_code.llm.google")


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
