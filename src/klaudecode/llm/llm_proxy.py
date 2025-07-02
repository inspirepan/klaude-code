import asyncio
import time
from abc import ABC, abstractmethod
from typing import AsyncGenerator, List, Optional, Tuple

import anthropic
import openai
from rich.text import Text

from ..message import AIMessage, BasicMessage
from ..tool import Tool
from ..tui import INTERRUPT_TIP, ColorStyle, console, render_dot_status, render_suffix
from ..utils.exception import format_exception
from .anthropic_proxy import AnthropicProxy
from .llm_proxy_base import DEFAULT_RETRIES, DEFAULT_RETRY_BACKOFF_BASE, LLMProxyBase
from .openai_proxy import OpenAIProxy
from .stream_status import StreamStatus, get_content_status_text, get_reasoning_status_text, get_tool_call_status_text, get_upload_status_text, text_status_str

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
    async def call(self, msgs: List[BasicMessage], tools: Optional[List[Tool]] = None) -> AIMessage:
        pass

    @abstractmethod
    async def stream_call(
        self,
        msgs: List[BasicMessage],
        tools: Optional[List[Tool]] = None,
        timeout: float = 20.0,
        interrupt_check: Optional[callable] = None,
    ) -> AsyncGenerator[Tuple[StreamStatus, AIMessage], None]:
        pass


class RetryWrapper(LLMClientWrapper):
    """Wrapper that adds retry logic to LLM calls"""

    def __init__(self, client: LLMProxyBase, max_retries: int = DEFAULT_RETRIES, backoff_base: float = DEFAULT_RETRY_BACKOFF_BASE):
        super().__init__(client)
        self.max_retries = max_retries
        self.backoff_base = backoff_base

    async def call(self, msgs: List[BasicMessage], tools: Optional[List[Tool]] = None) -> AIMessage:
        last_exception = None
        for attempt in range(self.max_retries):
            try:
                return await self.client.call(msgs, tools)
            except NON_RETRY_EXCEPTIONS as e:
                raise e
            except Exception as e:
                last_exception = e
                if attempt < self.max_retries - 1:
                    await self._handle_retry(attempt, e)

        self._handle_final_failure(last_exception)
        raise last_exception

    async def stream_call(
        self,
        msgs: List[BasicMessage],
        tools: Optional[List[Tool]] = None,
        timeout: float = 20.0,
        interrupt_check: Optional[callable] = None,
    ) -> AsyncGenerator[Tuple[StreamStatus, AIMessage], None]:
        last_exception = None
        for attempt in range(self.max_retries):
            try:
                async for item in self.client.stream_call(msgs, tools, timeout, interrupt_check):
                    yield item
                return
            except NON_RETRY_EXCEPTIONS as e:
                raise e
            except Exception as e:
                last_exception = e
                if attempt < self.max_retries - 1:
                    await self._handle_retry(attempt, e)

        self._handle_final_failure(last_exception)
        raise last_exception

    async def _handle_retry(self, attempt: int, exception: Exception):
        delay = self.backoff_base * (2**attempt)
        console.print(
            render_suffix(
                f'{format_exception(exception)} · Retrying in {delay:.1f} seconds... (attempt {attempt + 1}/{self.max_retries})',
                style=ColorStyle.ERROR,
            )
        )
        await asyncio.sleep(delay)

    def _handle_final_failure(self, exception: Exception):
        console.print(
            render_suffix(
                format_exception(exception),
                style=ColorStyle.ERROR,
            )
        )


class StatusWrapper(LLMClientWrapper):
    """Wrapper that adds status display to LLM calls"""

    async def call(self, msgs: List[BasicMessage], tools: Optional[List[Tool]] = None) -> AIMessage:
        with render_dot_status(status=get_content_status_text(), spinner_style=ColorStyle.CLAUDE, dots_style=ColorStyle.CLAUDE):
            ai_message = await self.client.call(msgs, tools)
        console.print()
        console.print(ai_message)
        return ai_message

    async def stream_call(
        self,
        msgs: List[BasicMessage],
        tools: Optional[List[Tool]] = None,
        timeout: float = 20.0,
        interrupt_check: Optional[callable] = None,
        status_text: Optional[str] = None,
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

        with render_dot_status(
            current_status_text,
            spinner_style=ColorStyle.CLAUDE,
            dots_style=ColorStyle.CLAUDE,
        ) as status:
            async for stream_status, ai_message in self.client.stream_call(msgs, tools, timeout, interrupt_check):
                ai_message: AIMessage
                if stream_status.phase == 'tool_call':
                    indicator = '⚒'
                    if stream_status.tool_names:
                        current_status_text = get_tool_call_status_text(stream_status.tool_names[-1], status_text_seed)
                elif stream_status.phase == 'upload':
                    indicator = '↑'
                elif stream_status.phase == 'think':
                    indicator = '✻'
                    current_status_text = reasoning_status_text
                else:
                    indicator = '↓'
                    current_status_text = content_status_text

                status.update(
                    status=current_status_text,
                    description=Text.assemble(
                        (f' {indicator} {stream_status.tokens} tokens', ColorStyle.SUCCESS),
                        (INTERRUPT_TIP, ColorStyle.MUTED),
                    ),
                )

                if stream_status.phase == 'tool_call' and not print_content_flag and ai_message.content:
                    console.print()
                    console.print(*ai_message.get_content_renderable())
                    print_content_flag = True
                if stream_status.phase in ['content', 'tool_call'] and not print_thinking_flag and ai_message.thinking_content:
                    console.print()
                    console.print(*ai_message.get_thinking_renderable())
                    print_thinking_flag = True

                yield stream_status, ai_message

        if not print_content_flag and ai_message and ai_message.content:
            console.print()
            console.print(*ai_message.get_content_renderable())


class LLMProxy:
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
        else:
            base_client = OpenAIProxy(model_name, base_url, api_key, model_azure, max_tokens, extra_header, extra_body, api_version, enable_thinking)

        self.client = RetryWrapper(base_client, max_retries, backoff_base)

    @property
    def model_name(self) -> str:
        return self.client.model_name

    async def call_with_retry(
        self,
        msgs: List[BasicMessage],
        tools: Optional[List[Tool]] = None,
        show_status: bool = True,
        use_streaming: bool = True,
        status_text: Optional[str] = None,
        timeout: float = 20.0,
        interrupt_check: Optional[callable] = None,
    ) -> AIMessage:
        if not show_status:
            return await self.client.call(msgs, tools)

        if not use_streaming:
            return await StatusWrapper(self.client).call(msgs, tools)

        ai_message = None
        async for stream_status, ai_message in StatusWrapper(self.client).stream_call(msgs, tools, timeout, interrupt_check, status_text):
            pass

        return ai_message
