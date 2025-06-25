import json
from enum import Enum
from functools import cached_property
from typing import Callable, Dict, List, Literal, Optional

from anthropic.types import ContentBlock, MessageParam, TextBlockParam, ToolUseBlockParam
from openai.types.chat import ChatCompletionMessageParam
from pydantic import BaseModel, Field
from rich.abc import RichRenderable
from rich.markup import escape
from rich.rule import Rule
from rich.text import Text

from .tui import ColorStyle, render_markdown, render_message, render_suffix, truncate_middle_text

INTERRUPTED_MSG = 'Interrupted by user'


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
    extra_data: Optional[dict] = None

    def get_content(self):
        """Get content in the format sent to LLM - should be overridden by subclasses"""
        return [{'type': 'text', 'text': self.content}]

    @property
    def tokens(self) -> int:
        """Get token count - calculated dynamically"""
        content_list = self.get_content()
        total_text = ''

        # Handle different content formats
        if isinstance(content_list, str):
            total_text = content_list
        elif isinstance(content_list, list):
            for item in content_list:
                if isinstance(item, dict):
                    if item.get('type') == 'text':
                        total_text += item.get('text', '')
                    elif item.get('type') == 'thinking':
                        total_text += item.get('thinking', '')
                    elif item.get('type') == 'tool_use':
                        # Add tool call text
                        tool_name = item.get('name', '')
                        tool_input = json.dumps(item.get('input', {})) if item.get('input') else ''
                        total_text += f'{tool_name}({tool_input})'
                elif isinstance(item, str):
                    total_text += item

        return count_tokens(total_text)

    def to_openai(self) -> ChatCompletionMessageParam:
        raise NotImplementedError

    def to_anthropic(self):
        raise NotImplementedError

    def set_extra_data(self, key: str, value: object):
        if not self.extra_data:
            self.extra_data = {}
        self.extra_data[key] = value

    def append_extra_data(self, key: str, value: object):
        if not self.extra_data:
            self.extra_data = {}
        if key not in self.extra_data:
            self.extra_data[key] = []
        self.extra_data[key].append(value)

    def get_extra_data(self, key: str, default: object = None) -> object:
        if not self.extra_data:
            return default
        if key not in self.extra_data:
            return default
        return self.extra_data[key]


class SystemMessage(BasicMessage):
    role: Literal['system'] = 'system'
    cached: bool = False

    def get_content(self):
        """Get system message content for OpenAI format"""
        return [
            {
                'type': 'text',
                'text': self.content,
                'cache_control': {'type': 'ephemeral'} if self.cached else None,
            }
        ]

    def get_anthropic_content(self):
        """Get system message content for Anthropic format"""
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

    def to_openai(self) -> ChatCompletionMessageParam:
        return {
            'role': 'system',
            'content': self.get_content(),
        }

    def to_anthropic(self) -> TextBlockParam:
        return self.get_anthropic_content()

    def __rich__(self):
        return ''  # System message is not displayed.

    def __bool__(self):
        return bool(self.content)


class SpecialUserMessageTypeEnum(Enum):
    INTERRUPTED = 'interrupted'
    COMPACT_RESULT = 'compact_result'


class UserMessage(BasicMessage):
    role: Literal['user'] = 'user'
    pre_system_reminders: Optional[List[str]] = None
    post_system_reminders: Optional[List[str]] = None
    user_msg_type: Optional[str] = None
    user_raw_input: Optional[str] = None

    def get_content(self):
        content_list = []
        if self.pre_system_reminders:
            for reminder in self.pre_system_reminders:
                content_list.append(
                    {
                        'type': 'text',
                        'text': reminder,
                    }
                )

        # Check if there's a custom content generator for this user message type
        main_content = self.content
        if self.user_msg_type and self.user_msg_type in _USER_MSG_CONTENT_FUNCS:
            main_content = _USER_MSG_CONTENT_FUNCS[self.user_msg_type](self)
        content_list.append(
            {
                'type': 'text',
                'text': main_content,
            }
        )
        if self.post_system_reminders:
            for reminder in self.post_system_reminders:
                content_list.append(
                    {
                        'type': 'text',
                        'text': reminder,
                    }
                )
        return content_list

    def to_openai(self) -> ChatCompletionMessageParam:
        return {'role': 'user', 'content': self.get_content()}

    def to_anthropic(self) -> MessageParam:
        return MessageParam(role='user', content=self.get_content())

    def __rich_console__(self, console, options):
        if not self.user_msg_type or self.user_msg_type not in _USER_MSG_RENDERERS:
            yield render_message(escape(self.content), mark='>')
        else:
            for item in _USER_MSG_RENDERERS[self.user_msg_type](self):
                yield item
        for item in self.get_suffix_renderable():
            yield item
        yield ''

    def get_suffix_renderable(self):
        if self.user_msg_type and self.user_msg_type in _USER_MSG_SUFFIX_RENDERERS:
            for item in _USER_MSG_SUFFIX_RENDERERS[self.user_msg_type](self):
                yield item
        if self.get_extra_data('error_msgs'):
            for error in self.get_extra_data('error_msgs'):
                yield render_suffix(error, style=ColorStyle.ERROR.value)

    def __bool__(self):
        return not self.removed and bool(self.content)

    def append_pre_system_reminder(self, reminder: str):
        if not self.pre_system_reminders:
            self.pre_system_reminders = [reminder]
        else:
            self.pre_system_reminders.append(reminder)

    def append_post_system_reminder(self, reminder: str):
        if not self.post_system_reminders:
            self.post_system_reminders = [reminder]
        else:
            self.post_system_reminders.append(reminder)


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
        return json.dumps(self.tool_args_dict, ensure_ascii=False) if self.tool_args_dict else ''

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
                    yield render_message(item, mark_style=ColorStyle.SUCCESS.value, status=self.status)
                else:
                    yield item
        else:
            msg = Text.assemble((self.tool_name, 'bold'), '(', self.tool_args, ')')
            yield render_message(msg, mark_style=ColorStyle.SUCCESS.value, status=self.status)

    def get_suffix_renderable(self):
        if self.tool_name in _TOOL_CALL_RENDERERS:
            for item in _TOOL_CALL_RENDERERS[self.tool_name](self):
                yield item
        else:
            yield Text.assemble((self.tool_name, 'bold'), '(', self.tool_args, ')')


class AIMessage(BasicMessage):
    role: Literal['assistant'] = 'assistant'
    tool_calls: Dict[str, ToolCall] = {}  # id -> ToolCall
    thinking_content: Optional[str] = None
    thinking_signature: Optional[str] = None
    finish_reason: Literal['stop', 'length', 'tool_calls', 'content_filter', 'function_call'] = 'stop'

    def get_content(self):
        """Get AI message content including thinking and tool calls for Anthropic"""
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
        return content

    def get_openai_content(self):
        """Get AI message content for OpenAI format"""
        result = {'role': 'assistant', 'content': self.content}
        if self.tool_calls:
            result['tool_calls'] = [tc.to_openai() for tc in self.tool_calls.values()]
        return result

    def to_openai(self) -> ChatCompletionMessageParam:
        return self.get_openai_content()

    def to_anthropic(self) -> MessageParam:
        return MessageParam(
            role='assistant',
            content=self.get_content(),
        )

    def __rich_console__(self, console, options):
        if self.thinking_content:
            yield render_message(
                Text('Thinking...', style=ColorStyle.AI_THINKING.value),
                mark='✻',
                mark_style=ColorStyle.AI_THINKING.value,
                style='italic',
            )
            yield render_message(
                Text(self.thinking_content, style=ColorStyle.AI_THINKING.value),
                mark='',
                style='italic',
                render_text=True,
            )
            yield ''
        if self.content:
            yield render_message(render_markdown(self.content), mark_style=ColorStyle.AI_MESSAGE, style=ColorStyle.AI_MESSAGE, render_text=True)
            yield ''

    def __bool__(self):
        return not self.removed and (bool(self.content) or bool(self.thinking_content) or bool(self.tool_calls))

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
    error_msg: Optional[str] = None
    system_reminders: Optional[List[str]] = None

    class Config:
        arbitrary_types_allowed = True

    @property
    def tool_call(self) -> ToolCall:
        return self.tool_call_cache

    def get_content(self):
        content_text = self.content
        if self.tool_call.status == 'canceled':
            content_text += '\n' + INTERRUPTED_MSG
        elif self.tool_call.status == 'error':
            content_text += '\nError: ' + self.error_msg
        content_list = [
            {
                'type': 'text',
                'text': content_text if content_text else '<system-reminder>Tool ran without output or errors</system-reminder>',
            }
        ]
        if self.system_reminders:
            for reminder in self.system_reminders:
                content_list.append(
                    {
                        'type': 'text',
                        'text': reminder,
                    }
                )
        return content_list

    def to_openai(self) -> ChatCompletionMessageParam:
        return {
            'role': 'tool',
            'content': self.get_content(),
            'tool_call_id': self.tool_call.id,
        }

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

    def get_suffix_renderable(self):
        if self.tool_call.tool_name in _TOOL_RESULT_RENDERERS:
            for item in _TOOL_RESULT_RENDERERS[self.tool_call.tool_name](self):
                yield item
        else:
            if self.content:
                yield render_suffix(
                    truncate_middle_text(self.content) if isinstance(self.content, str) else self.content,
                    style=ColorStyle.ERROR.value if self.tool_call.status == 'error' else None,
                )
            elif self.tool_call.status == 'success':
                yield render_suffix('(No content)')

        if self.tool_call.status == 'canceled':
            yield render_suffix(INTERRUPTED_MSG, style=ColorStyle.WARNING.value)
        elif self.tool_call.status == 'error':
            yield render_suffix(self.error_msg, style=ColorStyle.ERROR.value)
        yield ''

    def __rich_console__(self, console, options):
        yield self.tool_call
        for item in self.get_suffix_renderable():
            yield item

    def __bool__(self):
        return not self.removed and bool(self.get_content())

    def set_content(self, content: str):
        if self.tool_call.status == 'canceled':
            return
        self.content = content

    def set_error_msg(self, error_msg: str):
        self.error_msg = error_msg
        self.tool_call.status = 'error'

    def set_extra_data(self, key: str, value: object):
        if self.tool_call.status == 'canceled':
            return
        super().set_extra_data(key, value)

    def append_extra_data(self, key: str, value: object):
        if self.tool_call.status == 'canceled':
            return
        super().append_extra_data(key, value)

    def append_post_system_reminder(self, reminder: str):
        if not self.system_reminders:
            self.system_reminders = [reminder]
        else:
            self.system_reminders.append(reminder)


# Renderer Registry
# ---------------------

_TOOL_CALL_RENDERERS = {}
_TOOL_RESULT_RENDERERS = {}
_USER_MSG_RENDERERS = {}
_USER_MSG_SUFFIX_RENDERERS = {}
_USER_MSG_CONTENT_FUNCS = {}


def register_tool_call_renderer(tool_name: str, renderer_func: Callable[[ToolCall], RichRenderable]):
    _TOOL_CALL_RENDERERS[tool_name] = renderer_func


def register_tool_result_renderer(tool_name: str, renderer_func: Callable[[ToolMessage], RichRenderable]):
    _TOOL_RESULT_RENDERERS[tool_name] = renderer_func


def register_user_msg_suffix_renderer(user_msg_type: str, renderer_func: Callable[[UserMessage], RichRenderable]):
    _USER_MSG_SUFFIX_RENDERERS[user_msg_type] = renderer_func


def register_user_msg_renderer(user_msg_type: str, renderer_func: Callable[[UserMessage], RichRenderable]):
    _USER_MSG_RENDERERS[user_msg_type] = renderer_func


def register_user_msg_content_func(user_msg_type: str, content_func: Callable[['UserMessage'], str]):
    """Register a custom content generator for a specific user message type"""
    _USER_MSG_CONTENT_FUNCS[user_msg_type] = content_func


# Some Default User Message Type Renderers
# ---------------------


def interrupted_renderer(user_msg: UserMessage):
    yield render_message(INTERRUPTED_MSG, style=ColorStyle.ERROR.value, mark='>', mark_style=ColorStyle.ERROR.value)


def compact_renderer(user_msg: UserMessage):
    yield Rule(title=Text('Previous Conversation Compacted', ColorStyle.HIGHLIGHT.bold()), characters='=', style=ColorStyle.HIGHLIGHT.value)
    yield render_message(user_msg.content, mark='✻', mark_style=ColorStyle.AI_THINKING.value, style=ColorStyle.AI_THINKING.italic(), render_text=True)


register_user_msg_renderer(SpecialUserMessageTypeEnum.INTERRUPTED.value, interrupted_renderer)
register_user_msg_renderer(SpecialUserMessageTypeEnum.COMPACT_RESULT.value, compact_renderer)
