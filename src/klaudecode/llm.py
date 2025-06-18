import asyncio
from typing import Dict, List, Literal, Optional

import openai
from openai.types.chat import (ChatCompletionMessageParam,
                               ChatCompletionMessageToolCall)
from openai.types.chat.chat_completion_chunk import Choice, ChoiceDeltaToolCall
from openai.types.chat.chat_completion_message_tool_call import Function
from openai.types.completion_usage import CompletionUsage
from pydantic import BaseModel
from rich.status import Status

from .tui import console, render_message

# Lazy initialize tiktoken encoder for GPT-4
_encoder = None


def _get_encoder():
    global _encoder
    if _encoder is None:
        import tiktoken
        _encoder = tiktoken.encoding_for_model("gpt-4")
    return _encoder


def count_tokens(text: str) -> int:
    """Count tokens in text using tiktoken"""
    if not text:
        return 0
    return len(_get_encoder().encode(text))


class LLMResponse(BaseModel):
    content: str
    reasoning_content: str = ""
    tool_calls: Optional[List[ChatCompletionMessageToolCall]] = None
    usage: CompletionUsage
    finish_reason: Literal["stop", "length", "tool_calls", "content_filter", "function_call"]

    class Config:
        arbitrary_types_allowed = True


class LLMProxy:
    def __init__(
        self,
        model_name: str,
        base_url: str,
        api_key: str,
        model_azure: bool,
        max_tokens: int,
        extra_header: dict,
        enable_thinking: bool,
        max_retries=1,
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
        self.enable_thinking = enable_thinking
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
    ) -> LLMResponse:
        current_msgs = msgs.copy()
        completion = await self.client.chat.completions.create(
            model=self.model_name,
            messages=current_msgs,
            tools=tools,
            extra_headers=self.extra_header,
            max_tokens=self.max_tokens,
            extra_body={
                "thinking": {"type": "enabled", "budget_tokens": 2000}
            } if self.enable_thinking else None
        )
        message = completion.choices[0].message
        finish_reason = completion.choices[0].finish_reason
        tokens_used = completion.usage or CompletionUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0)
        reasoning_content = message.reasoning_content if hasattr(message, "reasoning_content") else ""
        return LLMResponse(
            content=message.content,
            tool_calls=message.tool_calls,
            reasoning_content=reasoning_content,
            usage=tokens_used,
            finish_reason=finish_reason,
        )

    async def _raw_stream_call(
        self,
        msgs: List[ChatCompletionMessageParam],
        tools: Optional[List[Dict]] = None,
        status: Optional[Status] = None
    ) -> LLMResponse:
        current_msgs = msgs.copy()
        stream = await self.client.chat.completions.create(
            model=self.model_name,
            messages=current_msgs,
            tools=tools,
            extra_headers=self.extra_header,
            max_tokens=self.max_tokens,
            stream=True,
            extra_body={
                "thinking": {"type": "enabled", "budget_tokens": 2000}
            } if self.enable_thinking else None
        )

        content = ""
        reasoning_content = ""
        tool_call_chunk_accumulator = ToolCallChunkAccumulator()
        finish_reason = "stop"
        completion_tokens = 0
        prompt_tokens = 0
        total_tokens = 0
        async for chunk in stream:
            if chunk.choices:
                choice: Choice = chunk.choices[0]
                if choice.delta.content:
                    content += choice.delta.content
                if hasattr(choice.delta, "reasoning_content") and choice.delta.reasoning_content:
                    reasoning_content += choice.delta.reasoning_content
                if choice.delta.tool_calls:
                    tool_call_chunk_accumulator.add_chunks(choice.delta.tool_calls)
                if choice.finish_reason:
                    finish_reason = choice.finish_reason
            if chunk.usage:
                usage: CompletionUsage = chunk.usage
                prompt_tokens = usage.prompt_tokens
                completion_tokens = usage.completion_tokens
                total_tokens = usage.total_tokens
                if status:
                    status.update(f"Thinking... [green]↓ {completion_tokens} tokens[/green] [gray]Press Ctrl+C to interrupt[/gray]")
            else:
                completion_tokens = count_tokens(content) + count_tokens(reasoning_content) + tool_call_chunk_accumulator.count_tokens()  # TODO: Optimize token count calc
                if status:
                    status.update(f"Thinking... [green]↓ {completion_tokens} tokens[/green] [gray]Press Ctrl+C to interrupt[/gray]")

        tokens_used = CompletionUsage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens
        )

        return LLMResponse(
            content=content,
            tool_calls=tool_call_chunk_accumulator.get_all_tool_calls(),
            reasoning_content=reasoning_content,
            usage=tokens_used,
            finish_reason=finish_reason,
        )

    async def _call_with_retry(
        self,
        msgs: List[ChatCompletionMessageParam],
        tools: Optional[List[Dict]] = None,
        show_status: bool = True,
        use_streaming: bool = True
    ) -> LLMResponse:
        last_exception = None
        for attempt in range(self.max_retries):
            try:
                if show_status:
                    if use_streaming:
                        with Status("Thinking... [gray]Press Ctrl+C to interrupt[/gray]", console=console.console, spinner_style="gray") as status:
                            return await self._raw_stream_call(msgs, tools, status)
                    else:
                        with Status("Thinking... [gray]Press Ctrl+C to interrupt[/gray]", console=console.console, spinner_style="gray"):
                            return await self._raw_call(msgs, tools)
                else:
                    if use_streaming:
                        return await self._raw_stream_call(msgs, tools, None)
                    else:
                        return await self._raw_call(msgs, tools)
            except (KeyboardInterrupt, asyncio.CancelledError):
                raise
            except Exception as e:
                last_exception = e
                if attempt < self.max_retries - 1:
                    delay = self.backoff_base * (2**attempt)
                    if show_status:
                        console.print(render_message(f"Retry {attempt + 1}/{self.max_retries}: call failed - {str(e)}, waiting {delay:.1f}s", status="error"), style="red")
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
        show_status: bool = True,
        use_streaming: bool = True
    ) -> LLMResponse:
        attempt = 0
        max_continuations = 3
        current_msgs = msgs.copy()
        full_content = ""
        full_reasoning_content = ""
        total_usage = CompletionUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0)
        final_tool_calls = None
        final_finish_reason = "stop"
        while attempt <= max_continuations:
            response = await self._call_with_retry(current_msgs, tools, show_status, use_streaming)
            total_usage.prompt_tokens += response.usage.prompt_tokens
            total_usage.completion_tokens += response.usage.completion_tokens
            total_usage.total_tokens += response.usage.total_tokens
            full_content += response.content
            full_reasoning_content += response.reasoning_content
            final_tool_calls = response.tool_calls
            final_finish_reason = response.finish_reason
            if response.finish_reason != "length":
                break
            attempt += 1
            if attempt > max_continuations:
                break
            if show_status:
                console.print(render_message("Continuing...", style="yellow"))
            current_msgs.append({"role": "assistant", "content": response.content})

        return LLMResponse(
            content=full_content,
            reasoning_content=full_reasoning_content,
            tool_calls=final_tool_calls,
            usage=total_usage,
            finish_reason=final_finish_reason,
        )


class LLM:
    """Singleton for every subclass"""

    _instances = {}
    _clients = {}

    def __new__(cls):
        if cls not in cls._instances:
            cls._instances[cls] = super().__new__(cls)
        return cls._instances[cls]

    @classmethod
    def initialize(
        cls,
        model_name: str,
        base_url: str,
        api_key: str,
        model_azure: bool,
        max_tokens: int,
        extra_header: dict,
        enable_thinking: bool
    ):
        instance = cls()
        cls._clients[cls] = LLMProxy(
            model_name=model_name,
            base_url=base_url,
            api_key=api_key,
            model_azure=model_azure,
            max_tokens=max_tokens,
            extra_header=extra_header,
            enable_thinking=enable_thinking,
        )
        return instance

    @classmethod
    def get_instance(cls) -> Optional["LLM"]:
        return cls._instances.get(cls)

    @property
    def client(self) -> Optional[LLMProxy]:
        return self._clients.get(self.__class__)

    @classmethod
    async def call(cls, msgs: List[ChatCompletionMessageParam], tools: Optional[List[Dict]] = None, show_status: bool = True, use_streaming: bool = True) -> LLMResponse:
        if cls not in cls._clients or cls._clients[cls] is None:
            raise RuntimeError("LLM client not initialized. Call initialize() first.")
        return await cls._clients[cls]._call_with_continuation(msgs, tools, show_status, use_streaming)

    @classmethod
    def reset(cls):
        if cls in cls._instances:
            del cls._instances[cls]
        if cls in cls._clients:
            del cls._clients[cls]


class AgentLLM(LLM):
    pass


class FastLLM(LLM):
    pass


class ToolCallChunkAccumulator:
    """
    WARNING: streaming is only tested for Claude, which returns tool calls in the specific sequence: tool_call_id, tool_call_name, followed by chunks of tool_call_args
    """

    def __init__(self):
        self.tool_call_list: List[ChatCompletionMessageToolCall] = []

    def add_chunks(self, chunks: Optional[List[ChoiceDeltaToolCall]]):
        if not chunks:
            return
        for chunk in chunks:
            self.add_chunk(chunk)

    def add_chunk(self, chunk: ChoiceDeltaToolCall):
        if not chunk:
            return
        if chunk.id:
            self.tool_call_list.append(ChatCompletionMessageToolCall(id=chunk.id, function=Function(arguments="", name="", type="function"), type="function"))
        if chunk.function.name and self.tool_call_list:
            self.tool_call_list[-1].function.name = chunk.function.name
        if chunk.function.arguments and self.tool_call_list:
            self.tool_call_list[-1].function.arguments += chunk.function.arguments

    def get_all_tool_calls(self) -> List[ChatCompletionMessageToolCall]:
        return self.tool_call_list

    def count_tokens(self):
        tokens = 0
        for tc in self.tool_call_list:
            tokens += count_tokens(tc.function.name) + count_tokens(tc.function.arguments)
        return tokens
