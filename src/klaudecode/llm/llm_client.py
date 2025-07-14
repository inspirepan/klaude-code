import asyncio
import os
import time
from abc import ABC, abstractmethod
from typing import AsyncGenerator, List, Optional, Tuple

import anthropic
import openai
from rich.text import Text

from ..message import AIMessage, BasicMessage
from ..tool import Tool
from ..tui import INTERRUPT_TIP, ColorStyle, console, render_dot_status, render_suffix
from ..tui.stream_status import StreamStatus, get_content_status_text, get_reasoning_status_text, get_tool_call_status_text, get_upload_status_text, text_status_str
from ..utils.exception import format_exception
from .llm_proxy_anthropic import AnthropicProxy
from .llm_proxy_base import DEFAULT_RETRIES, DEFAULT_RETRY_BACKOFF_BASE, LLMProxyBase
from .llm_proxy_gemini import GeminiProxy
from .llm_proxy_openai import OpenAIProxy

NON_RETRY_EXCEPTIONS = (
    KeyboardInterrupt,
    asyncio.CancelledError,
    openai.APIStatusError,
    anthropic.APIStatusError,
    openai.AuthenticationError,
    anthropic.AuthenticationError,
    openai.NotFoundError,
    anthropic.NotFoundError,
    openai.UnprocessableEntityError,
    anthropic.UnprocessableEntityError,
)


class LLMClientWrapper(ABC):
    """Base class for LLM client wrappers"""

    def __init__(self, client: LLMProxyBase):
        self.client = client

    @property
    def model_name(self) -> str:
        return self.client.model_name

    @abstractmethod
    async def stream_call(
        self,
        msgs: List[BasicMessage],
        tools: Optional[List[Tool]] = None,
        timeout: float = 20.0,
    ) -> AsyncGenerator[Tuple[StreamStatus, AIMessage], None]:
        pass


class RetryWrapper(LLMClientWrapper):
    """Wrapper that adds retry logic to LLM calls"""

    def __init__(self, client: LLMProxyBase, max_retries: int = DEFAULT_RETRIES, backoff_base: float = DEFAULT_RETRY_BACKOFF_BASE):
        super().__init__(client)
        self.max_retries = max_retries
        self.backoff_base = backoff_base

    async def stream_call(
        self,
        msgs: List[BasicMessage],
        tools: Optional[List[Tool]] = None,
        timeout: float = 20.0,
    ) -> AsyncGenerator[Tuple[StreamStatus, AIMessage], None]:
        last_exception = None
        for attempt in range(self.max_retries):
            try:
                async for item in self.client.stream_call(msgs, tools, timeout):
                    yield item
                return
            except NON_RETRY_EXCEPTIONS as e:
                raise e
            except Exception as e:
                last_exception = e
                if attempt < self.max_retries:
                    delay = self.backoff_base * (2**attempt)
                    error_msg = f'{format_exception(last_exception)} · Retrying in {delay:.1f} seconds... (attempt {attempt + 1}/{self.max_retries})'
                    error_msg = self.enhance_error_message(e, error_msg)

                    console.print(
                        render_suffix(
                            error_msg,
                            style=ColorStyle.ERROR,
                        )
                    )
                    await asyncio.sleep(delay)
        raise last_exception

    def enhance_error_message(self, exception, error_msg: str) -> str:
        if isinstance(exception, (openai.APIConnectionError, anthropic.APIConnectionError)):
            if os.environ.get('http_proxy') or os.environ.get('https_proxy') or os.environ.get('HTTP_PROXY') or os.environ.get('HTTPS_PROXY'):
                error_msg += ' · HTTP proxy detected, try disabling it'
        return error_msg


class StatusWrapper(LLMClientWrapper):
    """Wrapper that adds status display to LLM calls"""

    async def stream_call(
        self,
        msgs: List[BasicMessage],
        tools: Optional[List[Tool]] = None,
        timeout: float = 20.0,
        status_text: Optional[str] = None,
        show_result: bool = True,
    ) -> AsyncGenerator[Tuple[StreamStatus, AIMessage], None]:
        status_text_seed = int(time.time() * 1000) % 10000
        if status_text:
            reasoning_status_text = text_status_str(status_text)
            content_status_text = text_status_str(status_text)
            upload_status_text = text_status_str(status_text)
        else:
            reasoning_status_text = get_reasoning_status_text(status_text_seed)
            content_status_text = get_content_status_text(status_text_seed)
            upload_status_text = get_upload_status_text(status_text_seed)

        print_content_flag = False
        print_thinking_flag = False

        current_status_text = upload_status_text

        with render_dot_status(current_status_text) as status:
            async for stream_status, ai_message in self.client.stream_call(msgs, tools, timeout):
                ai_message: AIMessage
                if stream_status.phase == 'tool_call':
                    indicator = '⚒'
                    if stream_status.tool_names:
                        current_status_text = get_tool_call_status_text(stream_status.tool_names[-1], status_text_seed)
                elif stream_status.phase == 'upload':
                    indicator = ''
                elif stream_status.phase == 'think':
                    indicator = '✻'
                    current_status_text = reasoning_status_text
                elif stream_status.phase == 'content':
                    indicator = '↓'
                    current_status_text = content_status_text

                status.update(
                    status=current_status_text,
                    description=Text.assemble(
                        (f'{indicator}', ColorStyle.SUCCESS),
                        (f' {stream_status.tokens} tokens' if stream_status.tokens else '', ColorStyle.SUCCESS),
                        (INTERRUPT_TIP, ColorStyle.HINT),
                    ),
                )

                if show_result and stream_status.phase in ['tool_call', 'completed'] and not print_content_flag and ai_message.content:
                    console.print()
                    console.print(*ai_message.get_content_renderable())
                    print_content_flag = True
                if show_result and stream_status.phase in ['content', 'tool_call', 'completed'] and not print_thinking_flag and ai_message.thinking_content:
                    console.print()
                    console.print(*ai_message.get_thinking_renderable())
                    print_thinking_flag = True

                yield stream_status, ai_message


class LLMClient:
    def __init__(
        self,
        model_name: str,
        base_url: str,
        api_key: str,
        model_azure: bool,
        max_tokens: int,
        extra_header: dict,
        extra_body: dict,
        enable_thinking: bool,
        api_version: str,
        max_retries=DEFAULT_RETRIES,
        backoff_base=DEFAULT_RETRY_BACKOFF_BASE,
    ):
        if base_url == 'https://api.anthropic.com/v1/':
            base_client = AnthropicProxy(model_name, api_key, max_tokens, enable_thinking, extra_header, extra_body)
        elif 'gemini' in model_name.lower():
            base_client = GeminiProxy(model_name, base_url, api_key, model_azure, max_tokens, extra_header, extra_body, api_version, enable_thinking)
        else:
            base_client = OpenAIProxy(model_name, base_url, api_key, model_azure, max_tokens, extra_header, extra_body, api_version, enable_thinking)

        self.client = RetryWrapper(base_client, max_retries, backoff_base)

    @property
    def model_name(self) -> str:
        return self.client.model_name

    def cancel(self):
        """Cancel the current request"""
        # Find the base client and cancel it
        current_client = self.client
        while hasattr(current_client, 'client'):
            current_client = current_client.client
        if hasattr(current_client, 'cancel'):
            current_client.cancel()

    async def call(
        self,
        msgs: List[BasicMessage],
        tools: Optional[List[Tool]] = None,
        show_status: bool = True,
        show_result: bool = True,
        status_text: Optional[str] = None,
        timeout: float = 20.0,
    ) -> AIMessage:
        if not show_status:
            async for _, ai_message in self.client.stream_call(msgs, tools, timeout=timeout):
                pass
            return ai_message

        async for _, ai_message in StatusWrapper(self.client).stream_call(msgs, tools, timeout=timeout, status_text=status_text, show_result=show_result):
            pass
        return ai_message
