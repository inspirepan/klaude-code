import json
from typing import Any, List, Literal, Optional, Union

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
    content: Optional[str] = None
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


class ToolCallMessage(BaseModel):
    id: str
    tool_name: str
    tool_args: str = ''
    tool_args_dict: dict = {}
    status: Literal['processing', 'success', 'error'] = 'processing'
    hide_args: bool = False
    nice_args: str = ''
    rich_args: Optional[Any] = Field(default=None, exclude=True)

    def __init__(self, **data):
        super().__init__(**data)
        if self.tool_args and not self.tool_args_dict:
            try:
                self.tool_args_dict = json.loads(self.tool_args)
            except (json.JSONDecodeError, TypeError):
                self.tool_args_dict = {}
        elif self.tool_args_dict and not self.tool_args:
            self.tool_args = json.dumps(self.tool_args_dict)

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

    def __rich__(self):
        if self.rich_args:
            return Group(
                render_message(
                    format_style(self.tool_name, 'bold'),
                    mark_style='green',
                    status=self.status,
                ),
                self.rich_args,
            )
        if self.hide_args:
            return render_message(
                format_style(self.tool_name, 'bold'),
                mark_style='green',
                status=self.status,
            )
        msg = Text.assemble((self.tool_name, 'bold'), '(', self.nice_args or self.tool_args, ')')
        return render_message(msg, mark_style='green', status=self.status)

    def get_suffix_renderable(self) -> RichRenderable:
        args = '' if self.hide_args else self.nice_args or self.tool_args
        msg = Text.assemble((self.tool_name, 'bold'), '(', args, ')')
        return render_suffix(msg, error=self.status == 'error')


class AIMessage(BasicMessage):
    role: Literal['assistant'] = 'assistant'
    thinking_content: Optional[str] = ''
    tool_calls: dict[str, ToolCallMessage] = {}  # id -> ToolCall
    nice_content: Optional[str] = None
    # Used for Anthropic extended thinking
    thinking_signature: Optional[str] = ''
    finish_reason: Literal['stop', 'length', 'tool_calls', 'content_filter', 'function_call'] = 'stop'

    def __init__(self, **data):
        super().__init__(**data)
        if self.content and not self.nice_content:
            self.nice_content = render_markdown(self.content)

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
        if self.nice_content:
            yield render_message(self.nice_content, mark_style='white', style='orange')
            yield ''
        elif self.content:
            yield render_message(self.content, mark_style='white', style='orange')
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
    tool_call: ToolCallMessage
    subagent_tool_calls: List[ToolCallMessage] = Field(default_factory=list)  # For sub-agent tool calls

    class Config:
        arbitrary_types_allowed = True

    def to_openai(self) -> ChatCompletionMessageParam:
        return {
            'role': 'tool',
            'content': self.content,
            'tool_call_id': self.tool_call.id,
        }

    def to_anthropic(self) -> MessageParam:
        return MessageParam(
            role='user',
            content=[
                {
                    'type': 'tool_result',
                    'content': self.content,
                    'tool_use_id': self.tool_call.id,
                    'is_error': self.tool_call.status == 'error',
                }
            ],
        )

    def __rich_console__(self, console, options):
        yield self.tool_call
        for c in self.subagent_tool_calls:
            yield c.get_suffix_renderable()
        if self.content or self.tool_call.status == 'success':
            yield render_suffix(
                truncate_middle_text(self.content.strip()) if self.content else '(No content)',
                error=self.tool_call.status == 'error',
            )
        yield ''

    def __bool__(self):
        return bool(self.content)
