import asyncio
from typing import AsyncGenerator, Dict, List, Optional, Tuple

import openai
from openai.types.chat import ChatCompletionMessageToolCall
from openai.types.chat.chat_completion_chunk import Choice, ChoiceDeltaToolCall
from openai.types.chat.chat_completion_message_tool_call import Function

from ..message import AIMessage, BasicMessage, CompletionUsage, ToolCall, count_tokens
from ..tool import Tool
from .llm_proxy_base import LLMProxyBase
from .stream_status import StreamStatus


class OpenAIProxy(LLMProxyBase):
    def __init__(
        self,
        model_name: str,
        base_url: str,
        api_key: str,
        model_azure: bool,
        max_tokens: int,
        extra_header: dict,
        extra_body: dict,
        api_version: str,
        enable_thinking: Optional[bool] = None,
    ):
        super().__init__(model_name, max_tokens, extra_header, extra_body)
        self.base_url = base_url
        self.api_key = api_key
        self.model_azure = model_azure
        self.api_version = api_version
        self.enable_thinking = enable_thinking
        self.extra_body = extra_body.copy() if extra_body else {}

        if model_azure:
            self.client = openai.AsyncAzureOpenAI(
                azure_endpoint=self.base_url,
                api_version=self.api_version,
                api_key=self.api_key,
            )
        else:
            self.client = openai.AsyncOpenAI(
                base_url=self.base_url,
                api_key=self.api_key,
            )
        if 'thinking' not in self.extra_body:
            self.extra_body.update(
                {
                    'thinking': {
                        'type': 'auto' if self.enable_thinking is None else ('enabled' if self.enable_thinking else 'disabled'),
                    }
                }
            )

    async def call(self, msgs: List[BasicMessage], tools: Optional[List[Tool]] = None) -> AIMessage:
        completion = await self.client.chat.completions.create(
            model=self.model_name,
            messages=[msg.to_openai() for msg in msgs if msg],
            tools=[tool.openai_schema() for tool in tools] if tools else None,
            extra_headers=self.extra_header,
            extra_body=self.extra_body,
            max_tokens=self.max_tokens,
        )
        message = completion.choices[0].message
        tokens_used = None
        if completion.usage:
            tokens_used = CompletionUsage(
                completion_tokens=completion.usage.completion_tokens,
                prompt_tokens=completion.usage.prompt_tokens,
                total_tokens=completion.usage.total_tokens,
            )
        tool_calls = {}
        if message.tool_calls:
            tool_calls = {
                raw_tc.id: ToolCall(
                    id=raw_tc.id,
                    tool_name=raw_tc.function.name,
                    tool_args=raw_tc.function.arguments,
                )
                for raw_tc in message.tool_calls
            }
        return AIMessage(
            content=message.content,
            tool_calls=tool_calls,
            thinking_content=message.reasoning_content if hasattr(message, 'reasoning_content') else '',
            usage=tokens_used,
            finish_reason=completion.choices[0].finish_reason,
        )

    async def stream_call(
        self,
        msgs: List[BasicMessage],
        tools: Optional[List[Tool]] = None,
        timeout: float = 20.0,
        interrupt_check: Optional[callable] = None,
    ) -> AsyncGenerator[Tuple[StreamStatus, AIMessage], None]:
        stream_status = StreamStatus(phase='upload', tokens=sum(msg.tokens for msg in msgs if msg))
        yield (stream_status, AIMessage(content=''))

        stream = await asyncio.wait_for(
            self.client.chat.completions.create(
                model=self.model_name,
                messages=[msg.to_openai() for msg in msgs if msg],
                tools=[tool.openai_schema() for tool in tools] if tools else None,
                extra_headers=self.extra_header,
                max_tokens=self.max_tokens,
                extra_body=self.extra_body,
                stream=True,
            ),
            timeout=timeout,
        )

        content = ''
        thinking_content = ''
        tool_call_chunk_accumulator = self.OpenAIToolCallChunkAccumulator()
        finish_reason = 'stop'
        completion_tokens = 0
        prompt_tokens = 0
        total_tokens = 0
        async for chunk in stream:
            # Check for interruption at the start of each chunk
            if interrupt_check and interrupt_check():
                raise asyncio.CancelledError('Stream interrupted by user')

            if chunk.choices:
                choice: Choice = chunk.choices[0]
                if choice.delta.content:
                    stream_status.phase = 'content'
                    content += choice.delta.content
                if hasattr(choice.delta, 'reasoning_content') and choice.delta.reasoning_content:
                    stream_status.phase = 'think'
                    thinking_content += choice.delta.reasoning_content
                if choice.delta.tool_calls:
                    stream_status.phase = 'tool_call'
                    tool_call_chunk_accumulator.add_chunks(choice.delta.tool_calls)
                    stream_status.tool_names.extend([tc.function.name for tc in choice.delta.tool_calls if tc and tc.function and tc.function.name])
                if choice.finish_reason:
                    finish_reason = choice.finish_reason
                    stream_status.phase = 'completed'
            if chunk.usage:
                usage: CompletionUsage = chunk.usage
                prompt_tokens = usage.prompt_tokens
                completion_tokens = usage.completion_tokens
                total_tokens = usage.total_tokens
            else:
                completion_tokens = count_tokens(content) + count_tokens(thinking_content) + tool_call_chunk_accumulator.count_tokens()

            stream_status.tokens = completion_tokens
            yield (
                stream_status,
                AIMessage(
                    content=content,
                    thinking_content=thinking_content,
                    finish_reason=finish_reason,
                ),
            )

        tokens_used = CompletionUsage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
        )

        yield (
            stream_status,
            AIMessage(
                content=content,
                tool_calls=tool_call_chunk_accumulator.get_tool_call_msg_dict(),
                thinking_content=thinking_content,
                usage=tokens_used,
                finish_reason=finish_reason,
            ),
        )

    class OpenAIToolCallChunkAccumulator:
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
                self.tool_call_list.append(
                    ChatCompletionMessageToolCall(
                        id=chunk.id,
                        function=Function(arguments='', name='', type='function'),
                        type='function',
                    )
                )
            if chunk.function.name and self.tool_call_list:
                self.tool_call_list[-1].function.name = chunk.function.name
            if chunk.function.arguments and self.tool_call_list:
                self.tool_call_list[-1].function.arguments += chunk.function.arguments

        def get_tool_call_msg_dict(self) -> Dict[str, ToolCall]:
            return {
                raw_tc.id: ToolCall(
                    id=raw_tc.id,
                    tool_name=raw_tc.function.name,
                    tool_args=raw_tc.function.arguments,
                )
                for raw_tc in self.tool_call_list
            }

        def count_tokens(self):
            tokens = 0
            for tc in self.tool_call_list:
                tokens += count_tokens(tc.function.name) + count_tokens(tc.function.arguments)
            return tokens
