"""LLM package init.

Imports built-in LLM clients so their ``@register`` decorators run and they
become available via the registry.
"""

from .anthropic import AnthropicClient
from .client import LLMClientABC
from .openai_compatible import OpenAICompatibleClient
from .openrouter import OpenRouterClient
from .registry import create_llm_client
from .responses import ResponsesClient

__all__ = [
    "LLMClientABC",
    "ResponsesClient",
    "OpenAICompatibleClient",
    "OpenRouterClient",
    "AnthropicClient",
    "create_llm_client",
]
