import json
from functools import cached_property
from typing import Any, List, Literal, Optional, Union, Callable

from anthropic.types import (ContentBlock, MessageParam, TextBlockParam,
                             ToolUseBlockParam)
from openai.types.chat import ChatCompletionMessageParam
from pydantic import BaseModel, Field, computed_field, model_validator
from rich.abc import RichRenderable
from rich.console import Group
from rich.text import Text

from .config import ConfigModel
from .tui import (format_style, render_markdown, render_message, render_suffix,
                  truncate_middle_text)

INTERRUPTED_MSG = 'Task interrupted by user'


# Lazy initialize tiktoken encoder for GPT-4
_encoder = None


def _get_encoder():
    global _encoder
    if _encoder is None:
        import tiktoken

        _encoder = tiktoken.encoding_for_model('gpt-4')
    return _encoder


def count_tokens(text: str) -> int:
    """Count tokens in text using tiktoken"""
    if not text:
        return 0
    return len(_get_encoder().encode(text))


class CompletionUsage(BaseModel):
    completion_tokens: int
    prompt_tokens: int
    total_tokens: int


class BasicMessage(BaseModel):
    role: str
    content: str = ''
    removed: bool = False  # A message is removed when /compact called.
    usage: Optional[CompletionUsage] = None

    @computed_field
    @property
    def tokens(self) -> int:
        """Calculate token count for the message content"""
        return count_tokens(self.content)

    def to_openai(self) -> ChatCompletionMessageParam:
        raise NotImplementedError

    def to_anthropic(self):
        raise NotImplementedError


class SystemMessage(BasicMessage):
    role: Literal['system'] = 'system'
    cached: bool = False

    def to_openai(self) -> ChatCompletionMessageParam:
        return {
            'role': 'system',
            'content': [
                {
                    'type': 'text',
                    'text': self.content,
                    'cache_control': {'type': 'ephemeral'} if self.cached else None,
                }
            ],
        }

    def to_anthropic(self) -> TextBlockParam:
        if self.cached:
            return {
                'type': 'text',
                'text': self.content,
                'cache_control': {'type': 'ephemeral'},
            }
        return {
            'type': 'text',
            'text': self.content,
        }

    def __rich__(self):
        return ''  # System message is not displayed.

    def __bool__(self):
        return bool(self.content)


class UserMessage(BasicMessage):
    role: Literal['user'] = 'user'
    mode: Literal[
        'normal',
        'plan',
        'bash',
        'memory',
        'interrupted',
    ] = 'normal'
    suffix: Optional[Union[str, ConfigModel]] = None
    system_reminder: Optional[str] = None

    _mark_style: Optional[str] = None
    _mark: Optional[str] = None
    _style: Optional[str] = None

    _MODE_CONF = {
        'normal': {'_mark_style': None, '_mark': '>', '_style': None},
        'plan': {'_mark_style': None, '_mark': '>', '_style': None},
        'bash': {
            '_mark_style': 'magenta',
            '_mark': '!',
            '_style': 'magenta',
        },
        'memory': {'_mark_style': 'blue', '_mark': '#', '_style': 'blue'},
        'interrupted': {
            '_mark_style': 'yellow',
            '_mark': '⏺',
            '_style': 'yellow',
        },
    }

    @model_validator(mode='after')
    def _inject_private_defaults(self):
        conf = self._MODE_CONF[self.mode]
        for k, v in conf.items():
            setattr(self, k, v)
        return self

    def to_openai(self) -> ChatCompletionMessageParam:
        return {
            'role': 'user',
            'content': self.content,
        }  # TODO: add suffix and system_reminder

    def to_anthropic(self) -> MessageParam:
        return MessageParam(role='user', content=[{'type': 'text', 'text': self.content}])

    def __rich_console__(self, console, options):
        yield render_message(
            self.content,
            style=self._style,
            mark_style=self._mark_style,
            mark=self._mark,
        )
        if self.suffix:
            yield render_suffix(self.suffix)
        yield ''

    def __bool__(self):
        return bool(self.content)


class ToolCall(BaseModel):
    id: str
    tool_name: str
    tool_args_dict: dict = {}  # NOTE: This should only be set once during initialization
    status: Literal['processing', 'success', 'error', 'canceled'] = 'processing'

    @cached_property
    def tool_args(self) -> str:
        """
        Cached property that generates JSON string from dict only once.
        WARNING: Do not modify tool_args_dict after initialization as it will not update this cache.
        """
        return json.dumps(self.tool_args_dict) if self.tool_args_dict else ''

    def __init__(self, **data):
        # Handle legacy data with tool_args string field
        if 'tool_args' in data and not data.get('tool_args_dict'):
            tool_args_str = data.pop('tool_args')
            if tool_args_str:
                try:
                    data['tool_args_dict'] = json.loads(tool_args_str)
                except (json.JSONDecodeError, TypeError):
                    data['tool_args_dict'] = {}
        super().__init__(**data)

    @computed_field
    @property
    def tokens(self) -> int:
        func_tokens = count_tokens(self.tool_name)
        args_tokens = count_tokens(self.tool_args)
        return func_tokens + args_tokens

    def to_openai(self):
        return {
            'id': self.id,
            'type': 'function',
            'function': {
                'name': self.tool_name,
                'arguments': self.tool_args,
            },
        }

    def to_anthropic(self) -> ToolUseBlockParam:
        return {
            'id': self.id,
            'type': 'tool_use',
            'name': self.tool_name,
            'input': self.tool_args_dict,
        }

    def __rich_console__(self, console, options):
        if self.tool_name in _TOOL_CALL_RENDERERS:
            for i, item in enumerate(_TOOL_CALL_RENDERERS[self.tool_name](self)):
                if i == 0:
                    yield render_message(item, mark_style='green', status=self.status)
                else:
                    yield item
        else:
            msg = Text.assemble((self.tool_name, 'bold'), '(', self.tool_args, ')')
            yield render_message(msg, mark_style='green', status=self.status)

    def get_suffix_renderable(self):
        if self.tool_name in _TOOL_CALL_RENDERERS:
            for item in _TOOL_CALL_RENDERERS[self.tool_name](self):
                yield item
        else:
            yield Text.assemble((self.tool_name, 'bold'), '(', self.tool_args, ')')


class AIMessage(BasicMessage):
    role: Literal['assistant'] = 'assistant'
    tool_calls: dict[str, ToolCall] = {}  # id -> ToolCall
    thinking_content: Optional[str] = ''
    thinking_signature: Optional[str] = ''
    finish_reason: Literal['stop', 'length', 'tool_calls', 'content_filter', 'function_call'] = 'stop'

    @computed_field
    @property
    def tokens(self) -> int:
        """Calculate token count for AI message including tool calls"""
        content_tokens = count_tokens(self.content + self.thinking_content)
        tool_call_tokens = sum(tc.tokens for tc in self.tool_calls.values())
        return content_tokens + tool_call_tokens

    def to_openai(self) -> ChatCompletionMessageParam:
        result = {'role': 'assistant', 'content': self.content}
        if self.tool_calls:
            result['tool_calls'] = [tc.to_openai() for tc in self.tool_calls.values()]
        return result

    def to_anthropic(self) -> MessageParam:
        content: List[ContentBlock] = []
        if self.thinking_content:
            content.append(
                {
                    'type': 'thinking',
                    'thinking': self.thinking_content,
                    'signature': self.thinking_signature,
                }
            )
        if self.content:
            content.append(
                {
                    'type': 'text',
                    'text': self.content,
                }
            )
        if self.tool_calls:
            for tc in self.tool_calls.values():
                content.append(tc.to_anthropic())
        return MessageParam(
            role='assistant',
            content=content,
        )

    def __rich_console__(self, console, options):
        if self.thinking_content:
            yield render_message(
                format_style('Thinking...', 'gray'),
                mark='✻',
                mark_style='white',
                style='italic',
            )
            yield render_message(
                format_style(self.thinking_content, 'gray'),
                mark='',
                mark_style='white',
                style='italic',
            )
            yield ''
        elif self.content:
            yield render_message(render_markdown(self.content), mark_style='white', style='orange')
            yield ''

    def __bool__(self):
        return bool(self.content) or bool(self.thinking_content) or bool(self.tool_calls)

    def merge(self, other: 'AIMessage') -> 'AIMessage':
        self.content += other.content
        self.finish_reason = other.finish_reason
        self.tool_calls = other.tool_calls
        if other.thinking_content:
            self.thinking_content = other.thinking_content
            self.thinking_signature = other.thinking_signature
        if self.usage and other.usage:
            self.usage.completion_tokens += other.usage.completion_tokens
            self.usage.prompt_tokens += other.usage.prompt_tokens
            self.usage.total_tokens += other.usage.total_tokens
        self.tool_calls.update(other.tool_calls)
        return self


class ToolMessage(BasicMessage):
    role: Literal['tool'] = 'tool'
    tool_call_id: str
    tool_call_cache: ToolCall = Field(exclude=True)
    extra_data: List[Union[dict, str]] = Field(default_factory=list)
    error_msg: Optional[str] = None

    class Config:
        arbitrary_types_allowed = True

    @property
    def tool_call(self) -> ToolCall:
        return self.tool_call_cache

    def to_openai(self) -> ChatCompletionMessageParam:
        return {
            'role': 'tool',
            'content': self.content,
            'tool_call_id': self.tool_call.id,
        }

    def get_content(self):
        if self.tool_call.status == 'canceled':
            return self.content + '\n' + INTERRUPTED_MSG
        elif self.tool_call.status == 'error':
            return self.content + '\nError: ' + self.error_msg
        return self.content

    def to_anthropic(self) -> MessageParam:
        return MessageParam(
            role='user',
            content=[
                {
                    'type': 'tool_result',
                    'content': self.get_content(),
                    'tool_use_id': self.tool_call.id,
                    'is_error': self.tool_call.status == 'error',
                }
            ],
        )

    def __rich_console__(self, console, options):
        yield self.tool_call

        if self.tool_call.tool_name in _TOOL_RESULT_RENDERERS:
            for item in _TOOL_RESULT_RENDERERS[self.tool_call.tool_name](self):
                yield item
        else:
            if self.content:
                yield render_suffix(
                    truncate_middle_text(self.content) if isinstance(self.content, str) else self.content,
                    style='red' if self.tool_call.status == 'error' else None,
                )
            elif self.tool_call.status == 'success':
                yield render_suffix('(No content)')

        if self.tool_call.status == 'canceled':
            yield render_suffix(INTERRUPTED_MSG, style='yellow')
        elif self.tool_call.status == 'error':
            yield render_suffix(self.error_msg, style='red')
        yield ''

    def __bool__(self):
        return bool(self.content)

    def set_content(self, content: str):
        if self.tool_call.status == 'canceled':
            return
        self.content = content

    def set_error_msg(self, error_msg: str):
        self.error_msg = error_msg
        self.tool_call.status = 'error'

    def add_extra_data(self, extra_data: Union[dict, str]):
        """Convenience method to add structured data for custom rendering"""
        if self.tool_call.status == 'canceled':
            return
        self.extra_data.append(extra_data)

    def set_extra_data(self, extra_data: List[Union[dict, str]]):
        """Convenience method to add structured data for custom rendering"""
        if self.tool_call.status == 'canceled':
            return
        self.extra_data = extra_data


# Tool renderer registry for custom rendering
_TOOL_CALL_RENDERERS = {}
_TOOL_RESULT_RENDERERS = {}


def register_tool_call_renderer(tool_name: str, renderer_func: Callable[[ToolCall], RichRenderable]):
    _TOOL_CALL_RENDERERS[tool_name] = renderer_func


def register_tool_result_renderer(tool_name: str, renderer_func: Callable[[ToolMessage], RichRenderable]):
    _TOOL_RESULT_RENDERERS[tool_name] = renderer_func
