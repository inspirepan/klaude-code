import asyncio
from typing import AsyncGenerator, List, Literal, Optional, Tuple

import anthropic
from anthropic.types import MessageParam, RawMessageStreamEvent, StopReason, TextBlockParam

from ..message import AIMessage, BasicMessage, CompletionUsage, SystemMessage, ToolCall, count_tokens
from ..tool import Tool
from .llm_proxy_base import LLMProxyBase
from .stream_status import StreamStatus


class AnthropicProxy(LLMProxyBase):
    def __init__(
        self,
        model_name: str,
        api_key: str,
        max_tokens: int,
        enable_thinking: bool,
        extra_header: dict,
        extra_body: dict,
    ):
        super().__init__(model_name, max_tokens, extra_header, extra_body)
        self.api_key = api_key
        self.enable_thinking = enable_thinking
        self.client = anthropic.AsyncAnthropic(api_key=self.api_key)

    async def call(self, msgs: List[BasicMessage], tools: Optional[List[Tool]] = None) -> AIMessage:
        system_msgs, other_msgs = self.convert_to_anthropic(msgs)
        resp = await self.client.messages.create(
            model=self.model_name,
            max_tokens=self.max_tokens,
            thinking={
                'type': 'enabled' if self.enable_thinking else 'disabled',
                'budget_tokens': 2000,
            },
            tools=[tool.anthropic_schema() for tool in tools] if tools else None,
            messages=other_msgs,
            system=system_msgs,
            extra_headers=self.extra_header,
            extra_body=self.extra_body,
        )
        thinking_block = next((block for block in resp.content if block.type == 'thinking'), None)
        tool_use_blocks = [block for block in resp.content if block.type == 'tool_use']
        text_blocks = [block for block in resp.content if block.type != 'tool_use' and block.type != 'thinking']
        tool_calls = {
            tool_use.id: ToolCall(
                id=tool_use.id,
                tool_name=tool_use.name,
                tool_args_dict=tool_use.input,
            )
            for tool_use in tool_use_blocks
        }
        result = AIMessage(
            content='\n'.join([block.text for block in text_blocks]),
            thinking_content=thinking_block.thinking if thinking_block else '',
            thinking_signature=thinking_block.signature if thinking_block else '',
            tool_calls=tool_calls,
            finish_reason=self.convert_stop_reason(resp.stop_reason),
            usage=CompletionUsage(
                # TODO: cached prompt token
                completion_tokens=resp.usage.output_tokens,
                prompt_tokens=resp.usage.input_tokens,
                total_tokens=resp.usage.input_tokens + resp.usage.output_tokens,
            ),
        )
        return result

    async def stream_call(
        self,
        msgs: List[BasicMessage],
        tools: Optional[List[Tool]] = None,
        timeout: float = 20.0,
        interrupt_check: Optional[callable] = None,
    ) -> AsyncGenerator[Tuple[StreamStatus, AIMessage], None]:
        stream_status = StreamStatus(phase='upload', tokens=sum(msg.tokens for msg in msgs if msg))
        yield (stream_status, AIMessage(content=''))

        system_msgs, other_msgs = self.convert_to_anthropic(msgs)
        try:
            stream = await asyncio.wait_for(
                self.client.messages.create(
                    model=self.model_name,
                    max_tokens=self.max_tokens,
                    thinking={
                        'type': 'enabled' if self.enable_thinking else 'disabled',
                        'budget_tokens': 2000,
                    },
                    tools=[tool.anthropic_schema() for tool in tools] if tools else None,
                    messages=other_msgs,
                    system=system_msgs,
                    extra_headers=self.extra_header,
                    extra_body=self.extra_body,
                    stream=True,
                ),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            # Convert timeout to cancellation for consistency
            raise asyncio.CancelledError('Request timed out')

        content = ''
        thinking_content = ''
        thinking_signature = ''
        tool_calls = {}
        finish_reason = 'stop'
        input_tokens = 0
        output_tokens = 0
        content_blocks = {}
        tool_json_fragments = {}
        tool_call_tokens = 0

        async for event in stream:
            # Check for interruption at the start of each event
            if interrupt_check and interrupt_check():
                raise asyncio.CancelledError('Stream interrupted by user')

            event: RawMessageStreamEvent
            need_estimate = True
            if event.type == 'message_start':
                input_tokens = event.message.usage.input_tokens
                output_tokens = event.message.usage.output_tokens
            elif event.type == 'content_block_start':
                content_blocks[event.index] = event.content_block
                if event.content_block.type == 'thinking':
                    stream_status.phase = 'think'
                    thinking_signature = getattr(event.content_block, 'signature', '')
                elif event.content_block.type == 'tool_use':
                    stream_status.phase = 'tool_call'
                    # Initialize JSON fragment accumulator for tool use blocks
                    tool_json_fragments[event.index] = ''
                    if event.content_block.name:
                        stream_status.tool_names.append(event.content_block.name)
                else:
                    stream_status.phase = 'content'
            elif event.type == 'content_block_delta':
                if event.delta.type == 'text_delta':
                    content += event.delta.text
                elif event.delta.type == 'thinking_delta':
                    thinking_content += event.delta.thinking
                elif event.delta.type == 'signature_delta':
                    thinking_signature += event.delta.signature
                elif event.delta.type == 'input_json_delta':
                    # Accumulate JSON fragments for tool inputs
                    if event.index in tool_json_fragments:
                        tool_json_fragments[event.index] += event.delta.partial_json
                        tool_call_tokens += count_tokens(event.delta.partial_json)
            elif event.type == 'content_block_stop':
                # Use the tracked content block
                block = content_blocks.get(event.index)
                if block and block.type == 'tool_use':
                    # Get accumulated JSON fragments
                    json_str = tool_json_fragments.get(event.index, '{}')
                    tool_calls[block.id] = ToolCall(
                        id=block.id,
                        tool_name=block.name,
                        tool_args=json_str,
                    )
            elif event.type == 'message_delta':
                if hasattr(event.delta, 'stop_reason') and event.delta.stop_reason:
                    finish_reason = self.convert_stop_reason(event.delta.stop_reason)
                    stream_status.phase = 'completed'
                if hasattr(event, 'usage') and event.usage:
                    output_tokens = event.usage.output_tokens
                    need_estimate = False
            elif event.type == 'message_stop':
                pass

            if need_estimate:
                estimated_tokens = count_tokens(content) + count_tokens(thinking_content)
                for json_str in tool_json_fragments.values():
                    estimated_tokens += count_tokens(json_str)
                stream_status.tokens = estimated_tokens + tool_call_tokens
            yield (
                stream_status,
                AIMessage(
                    content=content,
                    thinking_content=thinking_content,
                    thinking_signature=thinking_signature,
                    finish_reason=finish_reason,
                ),
            )
        yield (
            stream_status,
            AIMessage(
                content=content,
                thinking_content=thinking_content,
                thinking_signature=thinking_signature,
                tool_calls=tool_calls,
                finish_reason=finish_reason,
                usage=CompletionUsage(
                    completion_tokens=output_tokens,
                    prompt_tokens=input_tokens,
                    total_tokens=input_tokens + output_tokens,
                ),
            ),
        )

    @staticmethod
    def convert_to_anthropic(
        msgs: List[BasicMessage],
    ) -> Tuple[List[TextBlockParam], List[MessageParam]]:
        system_msgs = [msg.to_anthropic() for msg in msgs if isinstance(msg, SystemMessage) if msg]
        other_msgs = [msg.to_anthropic() for msg in msgs if not isinstance(msg, SystemMessage) if msg]
        return system_msgs, other_msgs

    anthropic_stop_reason_openai_mapping = {
        'end_turn': 'stop',
        'max_tokens': 'length',
        'tool_use': 'tool_calls',
        'stop_sequence': 'stop',
    }

    @staticmethod
    def convert_stop_reason(
        stop_reason: Optional[StopReason],
    ) -> Literal['stop', 'length', 'tool_calls', 'content_filter', 'function_call']:
        if not stop_reason:
            return 'stop'
        return AnthropicProxy.anthropic_stop_reason_openai_mapping[stop_reason]
