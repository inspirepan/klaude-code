from typing import List, Literal, Optional

from anthropic.types import MessageParam
from openai.types.chat import ChatCompletionMessageParam
from pydantic import ConfigDict, Field

from ..tui import ColorStyle, render_suffix, truncate_middle_text
from .base import BasicMessage
from .tool_call import ToolCall

INTERRUPTED_MSG = 'Interrupted by user'
INTERRUPTED_CONTENT = '[Request interrupted by user for tool use]'
TRUNCATE_CHARS = 40100
TRUNCATE_POSTFIX = '... (truncated at 40100 characters)'


class ToolMessage(BasicMessage):
    role: Literal['tool'] = 'tool'
    tool_call_id: str
    tool_call_cache: ToolCall = Field(exclude=True)
    error_msg: Optional[str] = None
    system_reminders: Optional[List[str]] = None

    model_config = ConfigDict(arbitrary_types_allowed=True)

    @property
    def tool_call(self) -> ToolCall:
        return self.tool_call_cache

    def get_content(self):
        content_text = self.content
        if len(content_text) > TRUNCATE_CHARS:
            content_text = content_text[:TRUNCATE_CHARS] + '\n' + TRUNCATE_POSTFIX
        if self.tool_call.status == 'canceled':
            content_text = INTERRUPTED_CONTENT
        elif self.tool_call.status == 'error':
            content_text += '\nError: ' + self.error_msg

        content_list = [
            {
                'type': 'text',
                'text': content_text if content_text else '<system-reminder>Tool ran without output or errors</system-reminder>',
            }
        ]
        # Add attachments as separate content items
        if self.attachments:
            for attachment in self.attachments:
                content_list.extend(attachment.get_content())

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
        from .registry import _TOOL_RESULT_RENDERERS

        # Try exact match first
        if self.tool_call.tool_name in _TOOL_RESULT_RENDERERS:
            yield from _TOOL_RESULT_RENDERERS[self.tool_call.tool_name](self)
        else:
            # Try prefix match if exact match fails
            renderer_found = False
            for registered_name, renderer in _TOOL_RESULT_RENDERERS.items():
                if self.tool_call.tool_name.startswith(registered_name):
                    yield from renderer(self)
                    renderer_found = True
                    break

            if not renderer_found:
                if self.content:
                    yield render_suffix(
                        truncate_middle_text(self.content),
                        style=ColorStyle.ERROR if self.tool_call.status == 'error' else None,
                    )
                elif self.tool_call.status == 'success':
                    yield render_suffix('(No content)')
                elif self.tool_call.status == 'processing':
                    yield render_suffix('Running...')

        if self.tool_call.status == 'canceled':
            yield render_suffix(INTERRUPTED_MSG, style=ColorStyle.ERROR)
        elif self.tool_call.status == 'error':
            yield render_suffix(self.error_msg, style=ColorStyle.ERROR)

    def __rich_console__(self, console, options):
        yield self.tool_call
        yield from self.get_suffix_renderable()

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
