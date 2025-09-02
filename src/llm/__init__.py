"""LLM package init.

Ensures built-in clients are imported so their `@register` decorators run
and they become available via the registry.
"""

from .client import LLMClient
from .responses import ResponsesClient

__all__ = ["LLMClient", "ResponsesClient"]
