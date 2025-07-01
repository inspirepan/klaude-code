from typing import Dict, List, Literal, Optional

from anthropic.types import ContentBlock, MessageParam
from openai.types.chat import ChatCompletionMessageParam
from rich.text import Text

from ..tui import ColorStyle, render_markdown, render_message
from .base import BasicMessage
from .tool_call import ToolCall


class AIMessage(BasicMessage):
    role: Literal['assistant'] = 'assistant'
    tool_calls: Dict[str, ToolCall] = {}
    thinking_content: Optional[str] = None
    thinking_signature: Optional[str] = None
    finish_reason: Literal['stop', 'length', 'tool_calls', 'content_filter', 'function_call'] = 'stop'

    def get_content(self):
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
        for item in self.get_thinking_renderable():
            yield item
        for item in self.get_content_renderable():
            yield item

    def get_thinking_renderable(self):
        if self.thinking_content:
            yield render_message(
                Text('Thinking...', style=ColorStyle.AI_THINKING.value),
                mark='✻',
                mark_style=ColorStyle.AI_THINKING.value,
                style='italic',
            )
            yield ''
            yield render_message(
                Text(self.thinking_content, style=ColorStyle.AI_THINKING.value),
                mark='',
                style='italic',
                render_text=True,
            )

    def get_content_renderable(self):
        if self.content:
            yield render_message(render_markdown(self.content, style=ColorStyle.AI_MESSAGE.value), mark_style=ColorStyle.AI_MESSAGE, style=ColorStyle.AI_MESSAGE, render_text=True)

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
