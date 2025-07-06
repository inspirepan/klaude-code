import asyncio
from typing import AsyncGenerator, List, Literal, Optional, Tuple

import anthropic
from anthropic.types import MessageParam, RawMessageStreamEvent, StopReason, TextBlockParam

from ..message import AIMessage, BasicMessage, CompletionUsage, SystemMessage, ToolCall, UserMessage, count_tokens
from ..tool import Tool
from .llm_proxy_base import LLMProxyBase
from .stream_status import StreamStatus

TEMPERATURE = 1


class AnthropicProxy(LLMProxyBase):
    def get_think_budget(self, msgs: List[BasicMessage]) -> int:
        """Determine think budget based on user message keywords"""
        budget = 2000
        if msgs and isinstance(msgs[-1], UserMessage):
            content = msgs[-1].content.lower()
            if any(keyword in content for keyword in ['think harder', 'think intensely', 'think longer', 'think really hard', 'think super hard', 'think very hard', 'ultrathink']):
                budget = 31999
            elif any(keyword in content for keyword in ['think about it', 'think a lot', 'think deeply', 'think hard', 'think more', 'megathink']):
                budget = 10000
            elif 'think' in content:
                budget = 4000
        budget = min(self.max_tokens - 1000, budget)
        return budget

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
        self.enable_thinking = enable_thinking
        self.client = anthropic.AsyncAnthropic(api_key=api_key)

    async def stream_call(
        self,
        msgs: List[BasicMessage],
        tools: Optional[List[Tool]] = None,
        timeout: float = 20.0,
    ) -> AsyncGenerator[Tuple[StreamStatus, AIMessage], None]:
        stream_status = StreamStatus(phase='upload')
        yield (stream_status, AIMessage(content=''))

        system_msgs, other_msgs = self.convert_to_anthropic(msgs)
        budget_tokens = self.get_think_budget(msgs)

        try:
            self._current_request_task = asyncio.create_task(
                self.client.messages.create(
                    model=self.model_name,
                    max_tokens=self.max_tokens,
                    thinking={
                        'type': 'enabled' if self.enable_thinking else 'disabled',
                        'budget_tokens': budget_tokens,
                    },
                    tools=[tool.anthropic_schema() for tool in tools] if tools else None,
                    messages=other_msgs,
                    system=system_msgs,
                    extra_headers=self.extra_header,
                    extra_body=self.extra_body,
                    stream=True,
                    temperature=TEMPERATURE,
                )
            )

            try:
                stream = await asyncio.wait_for(self._current_request_task, timeout=timeout)
            finally:
                self._current_request_task = None
        except asyncio.TimeoutError:
            # Convert timeout to cancellation for consistency
            raise asyncio.CancelledError('Request timed out')

        ai_message = AIMessage()
        tool_calls = {}
        input_tokens = output_tokens = 0
        content_blocks = {}
        tool_json_fragments = {}

        async for event in stream:
            event: RawMessageStreamEvent

            # Check for cancellation at the beginning of each iteration
            if asyncio.current_task().cancelled():
                raise asyncio.CancelledError('Stream cancelled')

            need_estimate = True
            if event.type == 'message_start':
                input_tokens = event.message.usage.input_tokens
                output_tokens = event.message.usage.output_tokens
            elif event.type == 'content_block_start':
                content_blocks[event.index] = event.content_block
                if event.content_block.type == 'thinking':
                    stream_status.phase = 'think'
                    ai_message.thinking_signature = getattr(event.content_block, 'signature', '')
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
                    ai_message.content += event.delta.text
                elif event.delta.type == 'thinking_delta':
                    ai_message.thinking_content += event.delta.thinking
                elif event.delta.type == 'signature_delta':
                    ai_message.thinking_signature += event.delta.signature
                elif event.delta.type == 'input_json_delta':
                    # Accumulate JSON fragments for tool inputs
                    if event.index in tool_json_fragments:
                        tool_json_fragments[event.index] += event.delta.partial_json
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
                    ai_message.finish_reason = self.convert_stop_reason(event.delta.stop_reason)
                    stream_status.phase = 'completed'
                if hasattr(event, 'usage') and event.usage:
                    output_tokens = event.usage.output_tokens
                    stream_status.tokens = output_tokens
                    need_estimate = False
            elif event.type == 'message_stop':
                pass

            if need_estimate:
                estimated_tokens = ai_message.tokens
                for json_str in tool_json_fragments.values():
                    estimated_tokens += count_tokens(json_str)
                stream_status.tokens = estimated_tokens
            yield (stream_status, ai_message)
        ai_message.tool_calls = tool_calls
        ai_message.usage = CompletionUsage(
            completion_tokens=output_tokens,
            prompt_tokens=input_tokens,
            total_tokens=input_tokens + output_tokens,
        )
        yield (stream_status, ai_message)

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
