import asyncio
import time
from typing import List, Optional

import anthropic
import openai
from rich.text import Text

from ..message import AIMessage, BasicMessage
from ..tool import Tool, get_tool_call_status_text
from ..tui import INTERRUPT_TIP, ColorStyle, clear_last_line, console, render_status
from .anthropic_proxy import AnthropicProxy
from .llm_proxy_base import DEFAULT_RETRIES, DEFAULT_RETRY_BACKOFF_BASE, LLMProxyBase
from .openai_proxy import OpenAIProxy
from .stream_status import STATUS_TEXT_LENGTH, get_content_status_text, get_reasoning_status_text, get_upload_status_text

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
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        if base_url == 'https://api.anthropic.com/v1/':
            self.client = AnthropicProxy(model_name, api_key, max_tokens, enable_thinking, extra_header, extra_body)
        else:
            self.client = OpenAIProxy(model_name, base_url, api_key, model_azure, max_tokens, extra_header, extra_body, api_version, enable_thinking)
        self.client: LLMProxyBase

    async def _call_with_status(
        self,
        msgs: List[BasicMessage],
        tools: Optional[List[Tool]] = None,
        use_streaming: bool = True,
        status_text: Optional[str] = None,
        timeout: float = 20.0,
        interrupt_check: Optional[callable] = None,
    ) -> AIMessage:
        # Non-streaming mode
        if not use_streaming:
            with render_status(get_content_status_text().ljust(STATUS_TEXT_LENGTH)):
                ai_message = await self.client.call(msgs, tools)
            console.print(ai_message)
            return ai_message

        # Streaming mode
        status_text_seed = int(time.time() * 1000) % 10000
        if status_text:
            reasoning_status_text = status_text
            content_status_text = status_text
            upload_status_text = status_text
        else:
            reasoning_status_text = get_reasoning_status_text(status_text_seed)
            content_status_text = get_content_status_text(status_text_seed)
            upload_status_text = get_upload_status_text(status_text_seed)

        print_content_flag = False
        print_thinking_flag = False

        current_status_text = upload_status_text
        with render_status(
            Text(current_status_text.ljust(STATUS_TEXT_LENGTH), style=ColorStyle.AI_MESSAGE.value),
            spinner_style=ColorStyle.AI_MESSAGE.value,
        ) as status:
            async for stream_status, ai_message in self.client.stream_call(msgs, tools, timeout, interrupt_check):
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
                    Text.assemble(
                        Text(current_status_text.ljust(STATUS_TEXT_LENGTH), style=ColorStyle.AI_MESSAGE.value),
                        (f' {indicator} {stream_status.tokens} tokens', ColorStyle.SUCCESS.value),
                        (INTERRUPT_TIP, ColorStyle.MUTED.value),
                    ),
                    spinner_style=ColorStyle.AI_MESSAGE.value,
                )

                if stream_status.phase == 'tool_call' and not print_content_flag and ai_message.content:
                    console.print(*ai_message.get_content_renderable())
                    print_content_flag = True
                if stream_status.phase in ['content', 'tool_call'] and not print_thinking_flag and ai_message.thinking_content:
                    console.print(*ai_message.get_thinking_renderable())
                    print_thinking_flag = True

        if not print_content_flag and ai_message.content:
            console.print(*ai_message.get_content_renderable())
        return ai_message

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
        last_exception = None
        for attempt in range(self.max_retries):
            try:
                if not show_status:
                    return await self.client.call(msgs, tools)
                return await self._call_with_status(msgs, tools, use_streaming, status_text, timeout, interrupt_check)
            except NON_RETRY_EXCEPTIONS as e:
                # Handle cancellation and other non-retry exceptions immediately
                if isinstance(e, (asyncio.CancelledError, KeyboardInterrupt)):
                    # Clean up any status display
                    if show_status:
                        clear_last_line()
                raise e
            except Exception as e:
                last_exception = e
                delay = self.backoff_base * (2**attempt)
                if show_status:
                    if attempt == 0:
                        clear_last_line()
                    console.print(
                        f'Retry {attempt + 1}/{self.max_retries}: call {self.client.model_name} failed - {str(e)}, waiting {delay:.1f}s',
                        style=ColorStyle.ERROR.value,
                    )
                    with render_status(f'Waiting {delay:.1f}s...'):
                        await asyncio.sleep(delay)
                else:
                    await asyncio.sleep(delay)
            finally:
                if attempt > 0 and attempt < self.max_retries:
                    console.print()
        clear_last_line()
        console.print(
            f'Final failure: call {self.client.model_name} failed after {self.max_retries} retries - {last_exception}',
            style=ColorStyle.ERROR.value,
        )
        console.print()
        raise last_exception
