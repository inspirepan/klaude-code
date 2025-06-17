import asyncio
from typing import Dict, List, Literal, Optional, Tuple

import openai
from openai.types.chat import (ChatCompletionMessage,
                               ChatCompletionMessageParam,
                               ChatCompletionMessageToolCall, CompletionUsage)
from rich.status import Status

from .tui import console, format_style, render_message


class LLMProxy:
    def __init__(
        self,
        model_name: str,
        base_url: str,
        api_key: str,
        model_azure: bool,
        max_tokens: int,
        extra_header: dict,
    ):
        self.model_name = model_name
        self.base_url = base_url
        self.api_key = api_key
        self.model_azure = model_azure
        self.max_tokens = max_tokens
        self.extra_header = extra_header
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
        self, msgs: List[ChatCompletionMessageParam], tools: Optional[List[Dict]] = None
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

    async def _call_with_retry(self, msgs: List[ChatCompletionMessageParam], tools: Optional[List[Dict]] = None):
        retry_count = 4
        backoff = 1.0
        last_exception = None
        for attempt in range(retry_count):
            try:
                return await self._raw_call(msgs, tools)
            except (KeyboardInterrupt, asyncio.CancelledError):
                raise
            except Exception as e:
                last_exception = e
                if attempt < retry_count - 1:
                    delay = backoff * (2**attempt)
                    with Status(
                        render_message(
                            format_style(
                                f"Retry {attempt + 1}/{retry_count}: call failed - {str(e)}, waiting {delay:.1f}s",
                                "red",
                            ),
                            status="error",
                        )
                    ):
                        await asyncio.sleep(delay)
        console.print(
            render_message(
                f"Final failure: call failed after {retry_count} retries - {last_exception}",
                status="error",
            ),
        )
        raise last_exception


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
    async def call(cls, msgs: List[ChatCompletionMessageParam], tools: Optional[List[Dict]] = None):
        if cls._instance._client is None:
            raise RuntimeError("LLM client not initialized. Call initialize() first.")
        return await cls._instance._client._call_with_retry(msgs, tools)

    @classmethod
    def reset(cls):
        cls._instance = None
        cls._client = None
