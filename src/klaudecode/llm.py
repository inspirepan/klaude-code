from typing import Dict, List, Literal, Optional, Tuple
import asyncio
import openai
from openai.types.chat import ChatCompletionMessageParam, ChatCompletionMessageToolCall
from openai.types.completion_usage import CompletionUsage

from .tui import console, render_message
from rich.status import Status


class LLMProxy:
    def __init__(
        self,
        model_name: str,
        base_url: str,
        api_key: str,
        model_azure: bool,
        max_tokens: int,
        extra_header: dict,
        max_retries=5,
        backoff_base=1.0,
    ):
        self.model_name = model_name
        self.base_url = base_url
        self.api_key = api_key
        self.model_azure = model_azure
        self.max_tokens = max_tokens
        self.extra_header = extra_header
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        if model_azure:
            self.client = openai.AsyncAzureOpenAI(
                azure_endpoint=self.base_url,
                api_version="2024-03-01-preview",
                api_key=self.api_key,
            )
        else:
            self.client = openai.AsyncOpenAI(
                base_url=self.base_url,
                api_key=self.api_key,
            )

    async def _raw_call(
        self,
        msgs: List[ChatCompletionMessageParam],
        tools: Optional[List[Dict]] = None
    ) -> Tuple[str, Optional[List[ChatCompletionMessageToolCall]], CompletionUsage, Literal["stop", "length", "tool_calls", "content_filter", "function_call"]]:
        current_msgs = msgs.copy()
        completion = await self.client.chat.completions.create(
            model=self.model_name,
            messages=current_msgs,
            tools=tools,
            extra_headers=self.extra_header,
            max_tokens=self.max_tokens,
        )

        message = completion.choices[0].message
        finish_reason = completion.choices[0].finish_reason
        tokens_used = 0
        if hasattr(completion, "usage") and completion.usage:
            tokens_used = completion.usage
        return (
            message.content or "<empty>",
            message.tool_calls,
            tokens_used,
            finish_reason,
        )

    async def _call_with_retry(
        self,
        msgs: List[ChatCompletionMessageParam],
        tools: Optional[List[Dict]] = None,
        show_status: bool = True
    ) -> Tuple[str, Optional[List[ChatCompletionMessageToolCall]], CompletionUsage, Literal["stop", "length", "tool_calls", "content_filter", "function_call"]]:
        last_exception = None
        for attempt in range(self.max_retries):
            try:
                if show_status:
                    with Status(render_message("Thinking... [gray]Press Ctrl+C to interrupt.[/gray]"), console=console.console):
                        return await self._raw_call(msgs, tools)
                else:
                    return await self._raw_call(msgs, tools)
            except (KeyboardInterrupt, asyncio.CancelledError):
                raise
            except Exception as e:
                last_exception = e
                if attempt < self.max_retries - 1:
                    delay = self.backoff_base * (2**attempt)
                    if show_status:
                        console.print(render_message(f"Retry {attempt + 1}/{self.max_retries}: call failed - {str(e)}, waiting {delay:.1f}s"), style="red", status="error")
                        with Status(render_message(f"Waiting {delay:.1f}s...", style="red", status="error")):
                            await asyncio.sleep(delay)
                    else:
                        await asyncio.sleep(delay)
        console.print(render_message(f"Final failure: call failed after {self.max_retries} retries - {last_exception}", style="red", status="error"))
        raise last_exception

    async def _call_with_continuation(
        self,
        msgs: List[ChatCompletionMessageParam],
        tools: Optional[List[Dict]] = None,
        show_status: bool = True
    ) -> Tuple[str, Optional[List[ChatCompletionMessageToolCall]], CompletionUsage, Literal["stop", "length", "tool_calls", "content_filter", "function_call"]]:
        attempt = 0
        max_continuations = 3
        current_msgs = msgs.copy()
        full_content = ""
        total_usage = CompletionUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0)
        final_tool_calls = None
        final_finish_reason = "stop"
        while attempt <= max_continuations:
            content, tool_calls, usage, finish_reason = await self._call_with_retry(current_msgs, tools, show_status)
            if usage:
                total_usage.prompt_tokens += usage.prompt_tokens
                total_usage.completion_tokens += usage.completion_tokens
                total_usage.total_tokens += usage.total_tokens
            full_content += content
            final_tool_calls = tool_calls
            final_finish_reason = finish_reason
            if finish_reason != "length":
                break
            attempt += 1
            if attempt > max_continuations:
                break
            if show_status:
                console.print(render_message("Continuing...", style="yellow"))
            current_msgs.append({"role": "assistant", "content": content})
        return full_content, final_tool_calls, total_usage, final_finish_reason


class LLM:
    """Singleton"""

    _instance = None
    _client = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    def initialize(
        cls,
        model_name: str,
        base_url: str,
        api_key: str,
        model_azure: bool,
        max_tokens: int,
        extra_header: dict,
    ):
        instance = cls()
        instance._client = LLMProxy(
            model_name=model_name,
            base_url=base_url,
            api_key=api_key,
            model_azure=model_azure,
            max_tokens=max_tokens,
            extra_header=extra_header,
        )
        return instance

    @classmethod
    def get_instance(cls) -> Optional["LLM"]:
        return cls._instance

    @property
    def client(self) -> Optional[LLMProxy]:
        return self._client

    @classmethod
    async def call(cls, msgs: List[ChatCompletionMessageParam], tools: Optional[List[Dict]] = None, show_spinner: bool = True):
        if cls._instance._client is None:
            raise RuntimeError("LLM client not initialized. Call initialize() first.")
        return await cls._instance._client._call_with_continuation(msgs, tools, show_spinner)

    @classmethod
    def reset(cls):
        cls._instance = None
        cls._client = None
