import asyncio
from typing import Any, AsyncGenerator, Dict, List, Literal, Optional, Tuple

import anthropic
from anthropic.types import MessageParam, RawMessageStreamEvent, StopReason, TextBlockParam

from ..message import AIMessage, BasicMessage, CompletionUsage, SystemMessage, ToolCall, UserMessage, count_tokens
from ..tool import Tool
from ..tui.stream_status import StreamStatus
from .llm_proxy_base import LLMProxyBase

TEMPERATURE = 1


class StreamState:
    __slots__ = ['tool_calls', 'input_tokens', 'output_tokens', 'content_blocks', 'tool_json_fragments']

    def __init__(self) -> None:
        self.tool_calls: Dict[str, ToolCall] = {}
        self.input_tokens: int = 0
        self.output_tokens: int = 0
        self.content_blocks: Dict[int, Any] = {}
        self.tool_json_fragments: Dict[int, str] = {}


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
        extra_header: Dict[str, Any],
        extra_body: Dict[str, Any],
    ) -> None:
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

        stream = await self._create_stream(msgs, tools, timeout)
        ai_message = AIMessage()
        state = StreamState()

        try:
            # Set current task for immediate cancellation
            self._current_request_task = asyncio.current_task()

            async for event in stream:
                event: RawMessageStreamEvent
                if asyncio.current_task().cancelled():
                    raise asyncio.CancelledError('Stream cancelled')
                need_estimate = self._process_stream_event(event, stream_status, ai_message, state)

                if need_estimate:
                    stream_status.tokens = self._estimate_tokens(ai_message, state)

                yield (stream_status, ai_message)
        finally:
            self._current_request_task = None

        self._finalize_message(ai_message, state)
        yield (stream_status, ai_message)

    async def _create_stream(self, msgs: List[BasicMessage], tools: Optional[List[Tool]], timeout: float) -> AsyncGenerator[RawMessageStreamEvent, None]:
        system_msgs, other_msgs = self.convert_to_anthropic(msgs)
        budget_tokens = self.get_think_budget(msgs)

        try:
            # Create HTTP request task with immediate cancellation support
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
                # Use shield to ensure proper cleanup even if cancelled
                stream = await asyncio.shield(asyncio.wait_for(self._current_request_task, timeout=timeout))
                return stream
            except asyncio.CancelledError:
                # Ensure the request task is properly cancelled
                if self._current_request_task and not self._current_request_task.done():
                    self._current_request_task.cancel()
                    try:
                        await self._current_request_task
                    except asyncio.CancelledError:
                        pass
                raise
            finally:
                self._current_request_task = None
        except asyncio.TimeoutError:
            raise asyncio.CancelledError('Request timed out')

    def _process_stream_event(self, event: RawMessageStreamEvent, stream_status: StreamStatus, ai_message: AIMessage, state: StreamState) -> bool:
        need_estimate = True

        if event.type == 'message_start':
            self._handle_message_start(event, state)
        elif event.type == 'content_block_start':
            self._handle_content_block_start(event, stream_status, ai_message, state)
        elif event.type == 'content_block_delta':
            self._handle_content_block_delta(event, ai_message, state)
        elif event.type == 'content_block_stop':
            self._handle_content_block_stop(event, state)
        elif event.type == 'message_delta':
            need_estimate = self._handle_message_delta(event, stream_status, ai_message, state)
        elif event.type == 'message_stop':
            pass
        ai_message._invalidate_cache()
        return need_estimate

    def _handle_message_start(self, event: RawMessageStreamEvent, state: StreamState) -> None:
        state.input_tokens = event.message.usage.input_tokens
        state.output_tokens = event.message.usage.output_tokens

    def _handle_content_block_start(self, event: RawMessageStreamEvent, stream_status: StreamStatus, ai_message: AIMessage, state: StreamState) -> None:
        state.content_blocks[event.index] = event.content_block
        if event.content_block.type == 'thinking':
            stream_status.phase = 'think'
            ai_message.thinking_signature = getattr(event.content_block, 'signature', '')
        elif event.content_block.type == 'tool_use':
            stream_status.phase = 'tool_call'
            state.tool_json_fragments[event.index] = ''
            if event.content_block.name:
                stream_status.tool_names.append(event.content_block.name)
        else:
            stream_status.phase = 'content'

    def _handle_content_block_delta(self, event: RawMessageStreamEvent, ai_message: AIMessage, state: StreamState) -> None:
        if event.delta.type == 'text_delta':
            ai_message.content += event.delta.text
        elif event.delta.type == 'thinking_delta':
            ai_message.thinking_content += event.delta.thinking
        elif event.delta.type == 'signature_delta':
            ai_message.thinking_signature += event.delta.signature
        elif event.delta.type == 'input_json_delta':
            if event.index in state.tool_json_fragments:
                state.tool_json_fragments[event.index] += event.delta.partial_json

    def _handle_content_block_stop(self, event: RawMessageStreamEvent, state: StreamState) -> None:
        block = state.content_blocks.get(event.index)
        if block and block.type == 'tool_use':
            json_str = state.tool_json_fragments.get(event.index, '{}')
            state.tool_calls[block.id] = ToolCall(
                id=block.id,
                tool_name=block.name,
                tool_args=json_str,
            )

    def _handle_message_delta(self, event: RawMessageStreamEvent, stream_status: StreamStatus, ai_message: AIMessage, state: StreamState) -> bool:
        need_estimate = True
        if hasattr(event.delta, 'stop_reason') and event.delta.stop_reason:
            ai_message.finish_reason = self.convert_stop_reason(event.delta.stop_reason)
            stream_status.phase = 'completed'
        if hasattr(event, 'usage') and event.usage:
            state.output_tokens = event.usage.output_tokens
            stream_status.tokens = state.output_tokens
            need_estimate = False
        return need_estimate

    def _estimate_tokens(self, ai_message: AIMessage, state: StreamState) -> int:
        estimated_tokens = ai_message.tokens
        for json_str in state.tool_json_fragments.values():
            estimated_tokens += count_tokens(json_str)
        return estimated_tokens

    def _finalize_message(self, ai_message: AIMessage, state: StreamState) -> None:
        ai_message.tool_calls = state.tool_calls
        ai_message.usage = CompletionUsage(
            completion_tokens=state.output_tokens,
            prompt_tokens=state.input_tokens,
            total_tokens=state.input_tokens + state.output_tokens,
        )
        ai_message._invalidate_cache()

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
