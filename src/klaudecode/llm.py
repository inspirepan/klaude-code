import asyncio
from typing import Dict, List, Literal, Optional, Tuple

import anthropic
import openai
from anthropic.types import MessageParam, StopReason, TextBlockParam
from openai.types.chat import ChatCompletionMessageToolCall
from openai.types.chat.chat_completion_chunk import Choice, ChoiceDeltaToolCall
from openai.types.chat.chat_completion_message_tool_call import Function
from rich.status import Status
from rich.text import Text

from .message import AIMessage, BasicMessage, CompletionUsage, SystemMessage, ToolCall, count_tokens
from .tool import Tool
from .tui import INTERRUPT_TIP, ColorStyle, clear_last_line, console, render_message, render_status, render_suffix

DEFAULT_RETRIES = 3
DEFAULT_RETRY_BACKOFF_BASE = 0.5

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


class OpenAIProxy:
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
                api_version='2024-03-01-preview',
                api_key=self.api_key,
            )
        else:
            self.client = openai.AsyncOpenAI(
                base_url=self.base_url,
                api_key=self.api_key,
            )

    async def call(self, msgs: List[BasicMessage], tools: Optional[List[Tool]] = None) -> AIMessage:
        completion = await self.client.chat.completions.create(
            model=self.model_name,
            messages=[msg.to_openai() for msg in msgs if msg],
            tools=[tool.openai_schema() for tool in tools] if tools else None,
            extra_headers=self.extra_header,
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
        status: Optional[Status] = None,
        status_text: str = 'Thinking...',
        timeout: float = 20.0,
    ) -> AIMessage:
        # Calculate input tokens and show upload indicator
        input_tokens = sum(msg.tokens for msg in msgs if msg)
        if status:
            status.update(Text.assemble(status_text, (f' ↑ {input_tokens} tokens', ColorStyle.SUCCESS.value), (INTERRUPT_TIP, ColorStyle.MUTED.value)))

        stream = await asyncio.wait_for(
            self.client.chat.completions.create(
                model=self.model_name,
                messages=[msg.to_openai() for msg in msgs if msg],
                tools=[tool.openai_schema() for tool in tools] if tools else None,
                extra_headers=self.extra_header,
                max_tokens=self.max_tokens,
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
        has_tool_calls = False
        async for chunk in stream:
            if chunk.choices:
                choice: Choice = chunk.choices[0]
                if choice.delta.content:
                    content += choice.delta.content
                if hasattr(choice.delta, 'reasoning_content') and choice.delta.reasoning_content:
                    thinking_content += choice.delta.reasoning_content
                if choice.delta.tool_calls:
                    has_tool_calls = True
                    tool_call_chunk_accumulator.add_chunks(choice.delta.tool_calls)
                if choice.finish_reason:
                    finish_reason = choice.finish_reason
            if chunk.usage:
                usage: CompletionUsage = chunk.usage
                prompt_tokens = usage.prompt_tokens
                completion_tokens = usage.completion_tokens
                total_tokens = usage.total_tokens
                if status:
                    indicator = '⚒' if has_tool_calls else '↓'
                    status.update(Text.assemble(status_text, (f' {indicator} {completion_tokens} tokens', ColorStyle.SUCCESS.value), (INTERRUPT_TIP, ColorStyle.MUTED.value)))
            else:
                completion_tokens = count_tokens(content) + count_tokens(thinking_content) + tool_call_chunk_accumulator.count_tokens()
                if status:
                    indicator = '⚒' if has_tool_calls else '↓'
                    status.update(Text.assemble(status_text, (f' {indicator} {completion_tokens} tokens', ColorStyle.SUCCESS.value), (INTERRUPT_TIP, ColorStyle.MUTED.value)))

        tokens_used = CompletionUsage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
        )

        return AIMessage(
            content=content,
            tool_calls=tool_call_chunk_accumulator.get_tool_call_msg_dict(),
            thinking_content=thinking_content,
            usage=tokens_used,
            finish_reason=finish_reason,
        )

    class OpenAIToolCallChunkAccumulator:
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


class AnthropicProxy:
    def __init__(
        self,
        model_name: str,
        api_key: str,
        max_tokens: int,
        enable_thinking: bool,
        extra_header: dict,
    ):
        self.model_name = model_name
        self.api_key = api_key
        self.max_tokens = max_tokens
        self.enable_thinking = enable_thinking
        self.extra_header = extra_header
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
        status: Optional[Status] = None,
        status_text: str = 'Thinking...',
        timeout: float = 20.0,
    ) -> AIMessage:
        # Calculate input tokens and show upload indicator
        input_tokens = sum(msg.tokens for msg in msgs if msg)
        if status:
            status.update(Text.assemble(status_text, (f' ↑ {input_tokens} tokens', ColorStyle.SUCCESS.value), (INTERRUPT_TIP, ColorStyle.MUTED.value)))

        system_msgs, other_msgs = self.convert_to_anthropic(msgs)
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
                stream=True,
            ),
            timeout=timeout,
        )

        content = ''
        thinking_content = ''
        thinking_signature = ''
        tool_calls = {}
        finish_reason = 'stop'
        input_tokens = 0
        output_tokens = 0
        content_blocks = {}
        tool_json_fragments = {}
        has_tool_calls = False

        async for event in stream:
            if event.type == 'message_start':
                input_tokens = event.message.usage.input_tokens
                output_tokens = event.message.usage.output_tokens
            elif event.type == 'content_block_start':
                content_blocks[event.index] = event.content_block
                if event.content_block.type == 'thinking':
                    thinking_signature = getattr(event.content_block, 'signature', '')
                elif event.content_block.type == 'tool_use':
                    has_tool_calls = True
                    # Initialize JSON fragment accumulator for tool use blocks
                    tool_json_fragments[event.index] = ''
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
                if hasattr(event, 'usage') and event.usage:
                    output_tokens = event.usage.output_tokens
                    if status:
                        indicator = '⚒' if has_tool_calls else '↓'
                        status.update(Text.assemble(status_text, (f' {indicator} {output_tokens} tokens', ColorStyle.SUCCESS.value), (INTERRUPT_TIP, ColorStyle.MUTED.value)))
            elif event.type == 'message_stop':
                pass
            estimated_tokens = count_tokens(content) + count_tokens(thinking_content)
            for json_str in tool_json_fragments.values():
                estimated_tokens += count_tokens(json_str)
            if status and estimated_tokens:
                indicator = '⚒' if has_tool_calls else '↓'
                status.update(Text.assemble(status_text, (f' {indicator} {estimated_tokens} tokens', ColorStyle.SUCCESS.value), (INTERRUPT_TIP, ColorStyle.MUTED.value)))
        return AIMessage(
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
        max_retries=DEFAULT_RETRIES,
        backoff_base=DEFAULT_RETRY_BACKOFF_BASE,
    ):
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        if base_url == 'https://api.anthropic.com/v1/':
            self.client = AnthropicProxy(model_name, api_key, max_tokens, enable_thinking, extra_header)
        else:
            self.client = OpenAIProxy(model_name, base_url, api_key, model_azure, max_tokens, extra_header)

    async def _call_with_retry(
        self,
        msgs: List[BasicMessage],
        tools: Optional[List[Tool]] = None,
        show_status: bool = True,
        use_streaming: bool = True,
        status_text: str = 'Thinking...',
        timeout: float = 20.0,
    ) -> AIMessage:
        last_exception = None

        for attempt in range(self.max_retries):
            try:
                if show_status:
                    with render_status(status_text) as status:
                        if use_streaming:
                            return await self.client.stream_call(msgs, tools, status, status_text, timeout)
                        else:
                            return await self.client.call(msgs, tools)
                else:
                    if use_streaming:
                        return await self.client.stream_call(msgs, tools, None, timeout=timeout)
                    else:
                        return await self.client.call(msgs, tools)
            except NON_RETRY_EXCEPTIONS:
                raise
            except Exception as e:
                last_exception = e
                delay = self.backoff_base * (2**attempt)
                if show_status:
                    if attempt == 0:
                        clear_last_line()
                    console.print(
                        render_suffix(
                            f'Retry {attempt + 1}/{self.max_retries}: call {self.client.model_name} failed - {str(e)}, waiting {delay:.1f}s',
                            style=ColorStyle.ERROR.value,
                        )
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
            render_suffix(
                f'Final failure: call {self.client.model_name} failed after {self.max_retries} retries - {last_exception}',
                style=ColorStyle.ERROR.value,
            )
        )
        console.print()
        raise last_exception

    async def _call_with_continuation(
        self,
        msgs: List[BasicMessage],
        tools: Optional[List[Tool]] = None,
        show_status: bool = True,
        use_streaming: bool = True,
        status_text: str = 'Thinking...',
        timeout: float = 20.0,
    ) -> AIMessage:
        attempt = 0
        max_continuations = 3
        current_msgs = msgs.copy()
        merged_response = None
        while attempt <= max_continuations:
            response = await self._call_with_retry(current_msgs, tools, show_status, use_streaming, status_text, timeout)
            if merged_response is None:
                merged_response = response
            else:
                merged_response.merge(response)
            if response.finish_reason != 'length':
                break
            attempt += 1
            if attempt > max_continuations:
                break
            if show_status:
                console.print(render_message('Continuing...', style=ColorStyle.WARNING.value))
            current_msgs.append({'role': 'assistant', 'content': response.content})

        return merged_response


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
        enable_thinking: bool,
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
    def get_instance(cls) -> Optional['LLM']:
        return cls._instances.get(cls)

    @property
    def client(self) -> Optional[LLMProxy]:
        return self._clients.get(self.__class__)

    @classmethod
    async def call(
        cls,
        msgs: List[BasicMessage],
        tools: Optional[List[Tool]] = None,
        show_status: bool = True,
        status_text: str = 'Thinking...',
        use_streaming: bool = True,
        timeout: float = 20.0,
    ) -> AIMessage:
        if cls not in cls._clients or cls._clients[cls] is None:
            raise RuntimeError('LLM client not initialized. Call initialize() first.')
        return await cls._clients[cls]._call_with_continuation(msgs, tools, show_status, use_streaming, status_text, timeout)

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
