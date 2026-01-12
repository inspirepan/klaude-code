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
_PROTOCOL_MODULES: dict[llm_param.LLMClientProtocol, str] = {
    llm_param.LLMClientProtocol.ANTHROPIC: "klaude_code.llm.anthropic",
    llm_param.LLMClientProtocol.CLAUDE_OAUTH: "klaude_code.llm.claude",
    llm_param.LLMClientProtocol.BEDROCK: "klaude_code.llm.bedrock_anthropic",
    llm_param.LLMClientProtocol.CODEX_OAUTH: "klaude_code.llm.openai_codex",
    llm_param.LLMClientProtocol.OPENAI: "klaude_code.llm.openai_compatible",
    llm_param.LLMClientProtocol.OPENROUTER: "klaude_code.llm.openrouter",
    llm_param.LLMClientProtocol.RESPONSES: "klaude_code.llm.openai_responses",
    llm_param.LLMClientProtocol.GOOGLE: "klaude_code.llm.google",
    llm_param.LLMClientProtocol.ANTIGRAVITY: "klaude_code.llm.antigravity",
}


def _load_protocol(protocol: llm_param.LLMClientProtocol) -> None:
    """Load the module for a specific protocol on demand."""
    if protocol in _loaded_protocols:
        return
    module_path = _PROTOCOL_MODULES.get(protocol)
    if module_path is None:
        raise ValueError(f"Unknown LLMClient protocol: {protocol}")

    # Import only the needed module to trigger @register decorator
    importlib.import_module(module_path)
    _loaded_protocols.add(protocol)


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
