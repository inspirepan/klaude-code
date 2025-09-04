"""LLM package init.

Ensures built-in clients are imported so their `@register` decorators run
and they become available via the registry.
"""

from .anthropic import AnthropicClient
from .client import LLMClientABC
from .openai_compatible import OpenAICompatibleClient
from .registry import create_llm_client
from .responses import ResponsesClient

__all__ = [
    "LLMClientABC",
    "ResponsesClient",
    "OpenAICompatibleClient",
    "AnthropicClient",
    "create_llm_client",
]
