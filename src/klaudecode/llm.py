import asyncio
from typing import AsyncGenerator, Dict, List, Literal, Optional, Tuple

import anthropic
import openai
from anthropic.types import MessageParam, RawMessageStreamEvent, StopReason, TextBlockParam
from openai.types.chat import ChatCompletionMessageToolCall
from openai.types.chat.chat_completion_chunk import Choice, ChoiceDeltaToolCall
from openai.types.chat.chat_completion_message_tool_call import Function
from pydantic import BaseModel, Field
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


class StreamStatus(BaseModel):
    phase: Literal['upload', 'think', 'content', 'tool_call', 'completed'] = 'upload'
    tokens: int = 0
    tool_names: List[str] = Field(default_factory=list)


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
    ) -> AsyncGenerator[Tuple[StreamStatus, AIMessage], None]:
        stream_status = StreamStatus(tokens=sum(msg.tokens for msg in msgs))
        yield (stream_status, AIMessage(content=''))

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
        stream_status.phase = 'content'
        async for chunk in stream:
            if chunk.choices:
                choice: Choice = chunk.choices[0]
                if choice.delta.content:
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
        timeout: float = 20.0,
    ) -> AsyncGenerator[Tuple[StreamStatus, AIMessage], None]:
        stream_status = StreamStatus(tokens=sum(msg.tokens for msg in msgs))
        yield (stream_status, AIMessage(content=''))

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
        tool_call_tokens = 0
        stream_status.phase = 'content'

        async for event in stream:
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


def tool_call_status_text(tool_name: str) -> str:
    """
    Write -> Writing
    """
    if tool_name.endswith('e'):
        return f'{tool_name[:-1]}ing...'
    return f'{tool_name}ing...'


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
                if not show_status:
                    return await self.client.call(msgs, tools)
                if not use_streaming:
                    with render_status(status_text.ljust(15)):
                        ai_message = await self.client.call(msgs, tools)
                    console.print(ai_message)
                    return ai_message

                print_content_flag = False
                print_thinking_flag = False
                with render_status(status_text.ljust(15)) as status:
                    async for stream_status, ai_message in self.client.stream_call(msgs, tools, timeout):
                        indicator = '⚒' if stream_status.phase == 'tool_call' else '↑' if stream_status.phase == 'upload' else '↓'
                        current_status_text = (
                            tool_call_status_text(stream_status.tool_names[-1]) if stream_status.phase == 'tool_call' and stream_status.tool_names else status_text
                        )
                        status.update(
                            Text.assemble(
                                current_status_text.ljust(15), (f' {indicator} {stream_status.tokens} tokens', ColorStyle.SUCCESS.value), (INTERRUPT_TIP, ColorStyle.MUTED.value)
                            )
                        )
                        if stream_status.phase == 'tool_call' and not print_content_flag and ai_message.content:
                            console.print(*ai_message.get_content_renderable())
                            print_content_flag = True
                        if stream_status.phase == 'content' and not print_thinking_flag and ai_message.thinking_content:
                            console.print(*ai_message.get_thinking_renderable())
                            print_thinking_flag = True

                if not print_content_flag and ai_message.content:
                    console.print(*ai_message.get_content_renderable())
                return ai_message

            except NON_RETRY_EXCEPTIONS:
                raise
            except Exception as e:
                last_exception = e
                delay = self.backoff_base * (2**attempt)
                if show_status:
                    if attempt == 0:
                        clear_last_line()
                    import traceback

                    traceback.print_exc()
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
        """
        NOT USED. This method was designed to automatically continue generation when max_tokens is reached,
        but it undermines the user's control over max_tokens. Users should explicitly manage token limits
        rather than having implicit auto-continuation that bypasses their intended constraints.
        """
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
        return await cls._clients[cls]._call_with_retry(msgs, tools, show_status, use_streaming, status_text, timeout)

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


class LLMManager:
    """Thread-safe LLM connection pool manager"""

    def __init__(self):
        import threading

        self.client_pool = {}  # {thread_id: LLMProxy}
        self.config_cache = None  # Current configuration
        self._lock = threading.Lock()

    def initialize_from_config(self, config):
        """Initialize LLM manager from ConfigModel"""
        with self._lock:
            self.config_cache = {
                'model_name': config.model_name.value,
                'base_url': config.base_url.value,
                'api_key': config.api_key.value,
                'model_azure': config.model_azure.value,
                'max_tokens': config.max_tokens.value,
                'extra_header': config.extra_header.value,
                'enable_thinking': config.enable_thinking.value,
            }

    def get_client(self) -> LLMProxy:
        """Get LLM client for current thread"""
        import threading

        thread_id = threading.get_ident()

        if thread_id not in self.client_pool:
            if not self.config_cache:
                raise RuntimeError('LLMManager not initialized. Call initialize_from_config() first.')

            # Create new client for this thread
            self.client_pool[thread_id] = LLMProxy(
                model_name=self.config_cache['model_name'],
                base_url=self.config_cache['base_url'],
                api_key=self.config_cache['api_key'],
                model_azure=self.config_cache['model_azure'],
                max_tokens=self.config_cache['max_tokens'],
                extra_header=self.config_cache['extra_header'],
                enable_thinking=self.config_cache['enable_thinking'],
            )

        return self.client_pool[thread_id]

    async def call(
        self,
        msgs: List[BasicMessage],
        tools: Optional[List[Tool]] = None,
        show_status: bool = True,
        status_text: str = 'Thinking...',
        use_streaming: bool = True,
        timeout: float = 20.0,
    ) -> AIMessage:
        """Unified LLM call interface"""
        client = self.get_client()
        return await client._call_with_retry(msgs, tools, show_status, use_streaming, status_text, timeout)

    async def cleanup_thread(self, thread_id: int = None):
        """Clean up client for specific thread (or current thread)"""
        import threading

        if thread_id is None:
            thread_id = threading.get_ident()

        if thread_id in self.client_pool:
            client = self.client_pool[thread_id]
            # Proactively close HTTP client connections
            try:
                if hasattr(client.client, 'client'):
                    http_client = client.client.client
                    if hasattr(http_client, 'aclose'):
                        await http_client.aclose()
            except Exception:
                # Ignore cleanup errors
                pass
            del self.client_pool[thread_id]

    def reset(self):
        """Reset all clients and configuration"""
        with self._lock:
            self.client_pool.clear()
            self.config_cache = None
