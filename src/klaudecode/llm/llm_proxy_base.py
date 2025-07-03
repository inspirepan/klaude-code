from typing import AsyncGenerator, List, Optional, Tuple

from ..message import AIMessage, BasicMessage
from ..tool import Tool
from .stream_status import StreamStatus

DEFAULT_RETRIES = 3
DEFAULT_RETRY_BACKOFF_BASE = 0.5

BASE_EXTRA_HEADER = {
    # 'anthropic-beta': 'claude-code-20250219,interleaved-thinking-2025-05-14,fine-grained-tool-streaming-2025-05-14',
    'anthropic-beta': 'claude-code-20250219',
}


class LLMProxyBase:
    """Base class for LLM proxy implementations"""

    def __init__(self, model_name: str, max_tokens: int, extra_header: dict, extra_body: dict):
        self.model_name = model_name
        self.max_tokens = max_tokens
        extra_header.update(BASE_EXTRA_HEADER)
        self.extra_header = extra_header
        self.extra_body = extra_body

    async def call(self, msgs: List[BasicMessage], tools: Optional[List[Tool]] = None) -> AIMessage:
        """Make a non-streaming call to the LLM"""
        raise NotImplementedError

    async def stream_call(
        self,
        msgs: List[BasicMessage],
        tools: Optional[List[Tool]] = None,
        timeout: float = 20.0,
        interrupt_check: Optional[callable] = None,
    ) -> AsyncGenerator[Tuple[StreamStatus, AIMessage], None]:
        """Make a streaming call to the LLM"""
        raise NotImplementedError
