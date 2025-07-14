from enum import Enum
from typing import List, Literal, Optional

from anthropic.types import MessageParam
from openai.types.chat import ChatCompletionMessageParam
from rich.rule import Rule
from rich.text import Text

from ..tui import ColorStyle, render_markdown, render_message, render_suffix
from ..utils.file_utils import get_relative_path_for_display
from ..utils.str_utils import extract_xml_content
from .base import BasicMessage


class SpecialUserMessageTypeEnum(Enum):
    INTERRUPTED = 'interrupted'
    COMPACT_RESULT = 'compact_result'


class UserMessage(BasicMessage):
    role: Literal['user'] = 'user'
    pre_system_reminders: Optional[List[str]] = None
    post_system_reminders: Optional[List[str]] = None
    user_msg_type: Optional[str] = None
    user_raw_input: Optional[str] = None

    _openai_cache: Optional[dict] = None
    _anthropic_cache: Optional[dict] = None

    def get_content(self):
        if self._content_cache is not None:
            return self._content_cache

        from .registry import _USER_MSG_CONTENT_FUNCS

        content_list = []

        # Add pre-system reminders
        if self.pre_system_reminders:
            content_list.extend(
                {
                    'type': 'text',
                    'text': reminder,
                }
                for reminder in self.pre_system_reminders
            )

        # Add main content
        main_content = self.content
        if self.user_msg_type and self.user_msg_type in _USER_MSG_CONTENT_FUNCS:
            main_content = _USER_MSG_CONTENT_FUNCS[self.user_msg_type](self)

        content_list.append(
            {
                'type': 'text',
                'text': main_content,
            }
        )

        # Add attachments as separate content items
        if self.attachments:
            for attachment in self.attachments:
                content_list.extend(attachment.get_content())

        # Add post-system reminders
        if self.post_system_reminders:
            content_list.extend(
                {
                    'type': 'text',
                    'text': reminder,
                }
                for reminder in self.post_system_reminders
            )

        self._content_cache = content_list
        return content_list

    def to_openai(self) -> ChatCompletionMessageParam:
        if self._openai_cache is not None:
            return self._openai_cache

        result = {'role': 'user', 'content': self.get_content()}
        self._openai_cache = result
        return result

    def to_anthropic(self) -> MessageParam:
        if self._anthropic_cache is not None:
            return self._anthropic_cache

        result = MessageParam(role='user', content=self.get_content())
        self._anthropic_cache = result
        return result

    def __rich_console__(self, console, options):
        from .registry import _USER_MSG_RENDERERS

        if not self.user_msg_type or self.user_msg_type not in _USER_MSG_RENDERERS:
            yield render_message(
                Text(self.content, style=ColorStyle.USER_MESSAGE),
                mark='>',
            )
        else:
            yield from _USER_MSG_RENDERERS[self.user_msg_type](self)
        yield from self.get_suffix_renderable()

    def get_suffix_renderable(self):
        from .registry import _USER_MSG_SUFFIX_RENDERERS

        if self.user_msg_type and self.user_msg_type in _USER_MSG_SUFFIX_RENDERERS:
            yield from _USER_MSG_SUFFIX_RENDERERS[self.user_msg_type](self)

        # Render attachments
        if self.attachments:
            for attachment in self.attachments:
                display_path = get_relative_path_for_display(attachment.path)

                if attachment.type == 'directory':
                    attachment_text = Text.assemble('Listed directory ', (display_path + '/', ColorStyle.MAIN.bold))
                elif attachment.type == 'image':
                    attachment_text = Text.assemble('Read image ', (display_path, ColorStyle.MAIN.bold), f' ({attachment.size_str})' if attachment.size_str else '')
                else:
                    attachment_text = Text.assemble('Read ', (display_path, ColorStyle.MAIN.bold), f' ({attachment.line_count} lines)')
                yield render_suffix(attachment_text)

        if self.get_extra_data('error_msgs'):
            for error in self.get_extra_data('error_msgs'):
                yield render_suffix(error, style=ColorStyle.ERROR)

    def __bool__(self) -> bool:
        """
        For filtering out empty messages for LLM API calls
        """
        has_content = (self.content is not None) and len(self.content.strip()) > 0
        return not self.removed and has_content

    def is_valid(self) -> bool:
        """
        For filtering out empty messages for session saving
        """
        return (self.content is not None and len(self.content.strip()) > 0) or (self.user_raw_input is not None and len(self.user_raw_input.strip()) > 0)

    def append_pre_system_reminder(self, reminder: str):
        if not self.pre_system_reminders:
            self.pre_system_reminders = [reminder]
        else:
            self.pre_system_reminders.append(reminder)
        self._invalidate_cache()

    def append_post_system_reminder(self, reminder: str):
        if not self.post_system_reminders:
            self.post_system_reminders = [reminder]
        else:
            self.post_system_reminders.append(reminder)
        self._invalidate_cache()

    def _invalidate_cache(self):
        """Invalidate all caches when message is modified"""
        super()._invalidate_cache()
        self._openai_cache = None
        self._anthropic_cache = None


INTERRUPTED_MSG = 'Interrupted by user'


def interrupted_renderer(user_msg: 'UserMessage'):
    yield render_message(INTERRUPTED_MSG, style=ColorStyle.ERROR, mark='>', mark_style=ColorStyle.ERROR)


def compact_renderer(user_msg: 'UserMessage'):
    yield Rule(title=Text('Previous Conversation Compacted', ColorStyle.HIGHLIGHT.bold), characters='=', style=ColorStyle.HIGHLIGHT)
    summary = extract_xml_content(user_msg.content, 'summary')
    analysis = extract_xml_content(user_msg.content, 'analysis')
    markdown_content = render_markdown(f'### Analysis\n{analysis}\n\n### Summary\n{summary}', style=ColorStyle.AI_CONTENT.italic)

    yield render_message(
        markdown_content,
        mark='✻',
        mark_style=ColorStyle.HIGHLIGHT,
    )


def initialize_default_renderers():
    from .registry import register_user_msg_renderer

    register_user_msg_renderer(SpecialUserMessageTypeEnum.INTERRUPTED.value, interrupted_renderer)
    register_user_msg_renderer(SpecialUserMessageTypeEnum.COMPACT_RESULT.value, compact_renderer)


initialize_default_renderers()
