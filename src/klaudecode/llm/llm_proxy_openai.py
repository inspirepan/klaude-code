import asyncio
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple

import openai
from openai.types.chat import ChatCompletionChunk, ChatCompletionMessageToolCall
from openai.types.chat.chat_completion_chunk import ChoiceDeltaToolCall
from openai.types.chat.chat_completion_message_tool_call import Function

from ..message import (
    AIMessage,
    BasicMessage,
    CompletionUsage,
    ToolCall,
    add_cache_control,
    count_tokens,
    remove_cache_control,
)
from ..tool import Tool
from ..tui.stream_status import StreamStatus
from .llm_proxy_base import LLMProxyBase

TEMPERATURE = 1


class OpenAIProxy(LLMProxyBase):
    def __init__(
        self,
        model_name: str,
        base_url: str,
        api_key: str,
        model_azure: bool,
        max_tokens: int,
        extra_header: Dict[str, Any],
        extra_body: Dict[str, Any],
        api_version: str,
        enable_thinking: Optional[bool] = None,
    ) -> None:
        super().__init__(model_name, max_tokens, extra_header, extra_body)
        self.enable_thinking = enable_thinking  # TODO
        self.extra_body = extra_body.copy() if extra_body else {}

        if model_azure:
            self.client = openai.AsyncAzureOpenAI(
                azure_endpoint=base_url,
                api_version=api_version,
                api_key=api_key,
            )
        else:
            self.client = openai.AsyncOpenAI(
                base_url=base_url,
                api_key=api_key,
            )

    def _create_tool_call_accumulator(
        self,
    ) -> "OpenAIProxy.OpenAIToolCallChunkAccumulator":
        """Create the appropriate tool call accumulator. Override in subclasses."""
        return self.OpenAIToolCallChunkAccumulator()

    async def stream_call(
        self,
        msgs: List[BasicMessage],
        tools: Optional[List[Tool]] = None,
        timeout: float = 20.0,
    ) -> AsyncGenerator[Tuple[StreamStatus, AIMessage], None]:
        stream_status = StreamStatus(phase="upload")
        yield (stream_status, AIMessage(content=""))

        stream = await self._create_stream(msgs, tools, timeout)
        ai_message = AIMessage()

        tool_call_chunk_accumulator: "OpenAIProxy.OpenAIToolCallChunkAccumulator" = (
            self._create_tool_call_accumulator()
        )

        prompt_tokens = completion_tokens = total_tokens = 0

        try:
            # Set current task for immediate cancellation
            self._current_request_task = asyncio.current_task()

            async for chunk in stream:
                chunk: ChatCompletionChunk
                if asyncio.current_task().cancelled():
                    raise asyncio.CancelledError("Stream cancelled")
                prompt_tokens, completion_tokens, total_tokens = self._process_chunk(
                    chunk,
                    stream_status,
                    ai_message,
                    tool_call_chunk_accumulator,
                    prompt_tokens,
                    completion_tokens,
                    total_tokens,
                )
                yield (stream_status, ai_message)
        finally:
            self._current_request_task = None

        self._finalize_message(
            ai_message,
            tool_call_chunk_accumulator,
            prompt_tokens,
            completion_tokens,
            total_tokens,
        )
        yield (stream_status, ai_message)

    async def _create_stream(
        self, msgs: List[BasicMessage], tools: Optional[List[Tool]], timeout: float
    ) -> AsyncGenerator[ChatCompletionChunk, None]:
        msgs = [msg.to_openai() for msg in msgs if msg]
        if msgs:
            msgs[-1] = add_cache_control(msgs[-1])

        # Create HTTP request task with immediate cancellation support
        self._current_request_task = asyncio.create_task(
            self.client.chat.completions.create(
                model=self.model_name,
                messages=msgs,
                tools=[tool.openai_schema() for tool in tools] if tools else None,
                extra_headers=self.extra_header,
                max_tokens=self.max_tokens,
                extra_body=self.extra_body,
                stream=True,
                temperature=TEMPERATURE,
            )
        )

        if msgs:
            msgs[-1] = remove_cache_control(msgs[-1])

        try:
            stream = await asyncio.wait_for(self._current_request_task, timeout=timeout)
            return stream
        except asyncio.CancelledError:
            if self._current_request_task and not self._current_request_task.done():
                self._current_request_task.cancel()
                try:
                    await self._current_request_task
                except asyncio.CancelledError:
                    pass
            raise
        finally:
            self._current_request_task = None

    def _process_chunk(
        self,
        chunk: ChatCompletionChunk,
        stream_status: StreamStatus,
        ai_message: AIMessage,
        tool_call_chunk_accumulator,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
    ) -> Tuple[int, int, int]:
        if chunk.choices:
            self._handle_choice_delta(
                chunk.choices[0], stream_status, ai_message, tool_call_chunk_accumulator
            )

        if chunk.usage:
            prompt_tokens, total_tokens = (
                chunk.usage.prompt_tokens,
                chunk.usage.total_tokens,
            )

        completion_tokens = self._calculate_completion_tokens(
            chunk, ai_message, tool_call_chunk_accumulator, completion_tokens
        )

        stream_status.tokens = completion_tokens

        return prompt_tokens, completion_tokens, total_tokens

    def _handle_choice_delta(
        self,
        choice: Any,
        stream_status: StreamStatus,
        ai_message: AIMessage,
        tool_call_chunk_accumulator,
    ) -> None:
        if choice.delta.content:
            stream_status.phase = "content"
            ai_message.append_content_chunk(choice.delta.content)

        if (
            hasattr(choice.delta, "reasoning_content")
            and choice.delta.reasoning_content
        ):
            stream_status.phase = "think"
            ai_message.append_thinking_content_chunk(choice.delta.reasoning_content)

        if choice.delta.tool_calls:
            stream_status.phase = "tool_call"
            tool_call_chunk_accumulator.add_chunks(choice.delta.tool_calls)
            stream_status.tool_names.extend(
                [
                    tc.function.name
                    for tc in choice.delta.tool_calls
                    if tc and tc.function and tc.function.name
                ]
            )

        if choice.finish_reason:
            ai_message.finish_reason = choice.finish_reason
            stream_status.phase = "completed"

        ai_message._invalidate_cache()

    def _calculate_completion_tokens(
        self,
        chunk: ChatCompletionChunk,
        ai_message: AIMessage,
        tool_call_chunk_accumulator,
        current_tokens: int,
    ) -> int:
        if chunk.usage and chunk.usage.completion_tokens:
            return chunk.usage.completion_tokens
        else:
            return ai_message.tokens + tool_call_chunk_accumulator.count_tokens()

    def _finalize_message(
        self,
        ai_message: AIMessage,
        tool_call_chunk_accumulator: "OpenAIProxy.OpenAIToolCallChunkAccumulator",
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
    ) -> None:
        ai_message.tool_calls = tool_call_chunk_accumulator.get_tool_call_dict()
        ai_message.usage = CompletionUsage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
        )
        ai_message._invalidate_cache()
        ai_message.content = ai_message.content.strip()
        ai_message.thinking_content = ai_message.thinking_content.strip()
        ai_message.status = "success"

    class OpenAIToolCallChunkAccumulator:
        def __init__(self) -> None:
            self.tool_call_list: List[ChatCompletionMessageToolCall] = []

        def add_chunks(self, chunks: Optional[List[ChoiceDeltaToolCall]]) -> None:
            if not chunks:
                return
            for chunk in chunks:
                self.add_chunk(chunk)

        def add_chunk(self, chunk: ChoiceDeltaToolCall) -> None:
            if not chunk:
                return
            if chunk.id:
                self._add_new_tool_call(chunk.id)
            if chunk.function.name and self.tool_call_list:
                self._update_tool_name(chunk.function.name)
            if chunk.function.arguments and self.tool_call_list:
                self._update_tool_arguments(chunk.function.arguments)

        def _add_new_tool_call(self, tool_id: str) -> None:
            """Add a new tool call with the given ID."""
            self.tool_call_list.append(
                ChatCompletionMessageToolCall(
                    id=tool_id,
                    function=Function(arguments="", name=""),
                    type="function",
                )
            )

        def _update_tool_name(self, name: str) -> None:
            """Update the name of the last tool call."""
            self.tool_call_list[-1].function.name = name

        def _update_tool_arguments(self, arguments: str) -> None:
            """Update the arguments of the last tool call (append for streaming)."""
            self.tool_call_list[-1].function.arguments += arguments

        def get_tool_call_dict(self) -> Dict[str, ToolCall]:
            result = {}
            for raw_tc in self.tool_call_list:
                try:
                    result[raw_tc.id] = ToolCall(
                        id=raw_tc.id,
                        tool_name=raw_tc.function.name,
                        tool_args=raw_tc.function.arguments,
                    )
                except Exception as e:
                    from ..tui import ColorStyle, render_suffix

                    render_suffix(
                        f"Error processing tool call: {e}", style=ColorStyle.ERROR
                    )
                    continue
            return result

        def count_tokens(self) -> int:
            tokens = 0
            for tc in self.tool_call_list:
                tokens += count_tokens(tc.function.name) + count_tokens(
                    tc.function.arguments
                )
            return tokens
