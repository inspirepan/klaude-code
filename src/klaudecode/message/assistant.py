from typing import Dict, List, Literal, Optional

from anthropic.types import ContentBlock, MessageParam
from openai.types.chat import ChatCompletionMessageParam
from pydantic import BaseModel
from rich.text import Text

from ..tui import ColorStyle, render_markdown, render_message
from .base import BasicMessage
from .tool_call import ToolCall


class CompletionUsage(BaseModel):
    completion_tokens: int
    prompt_tokens: int
    total_tokens: int


class AIMessage(BasicMessage):
    role: Literal['assistant'] = 'assistant'
    tool_calls: Dict[str, ToolCall] = {}
    thinking_content: Optional[str] = None
    thinking_signature: Optional[str] = None
    finish_reason: Literal['stop', 'length', 'tool_calls', 'content_filter', 'function_call'] = 'stop'
    usage: Optional[CompletionUsage] = None

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
        yield from self.get_thinking_renderable()
        yield from self.get_content_renderable()

    def get_thinking_renderable(self):
        if self.thinking_content:
            yield render_message(
                Text('Thinking...', style=ColorStyle.AI_THINKING),
                mark='✻',
                mark_style=ColorStyle.AI_THINKING,
                style='italic',
            )
            yield ''
            yield render_message(
                Text(self.thinking_content, style=ColorStyle.AI_THINKING),
                mark='',
                style='italic',
                render_text=True,
            )

    def get_content_renderable(self):
        if self.content:
            yield render_message(render_markdown(self.content, style=ColorStyle.AI_MESSAGE), mark_style=ColorStyle.AI_MESSAGE, style=ColorStyle.AI_MESSAGE, render_text=True)

    def __bool__(self):
        return not self.removed and (bool(self.content) or bool(self.thinking_content) or bool(self.tool_calls))

    def merge(self, other: 'AIMessage') -> 'AIMessage':
        """
        # For message continuation, not currently used
        """
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


class AgentUsage(BaseModel):
    total_llm_calls: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0

    def update(self, ai_message: AIMessage):
        self.total_llm_calls += 1
        if ai_message.usage:
            self.total_input_tokens += ai_message.usage.prompt_tokens
            self.total_output_tokens += ai_message.usage.completion_tokens

    def __rich_console__(self, console, options):
        from rich.console import Group

        yield Group(
            Text(f'Total LLM calls:     {self.total_llm_calls:<10}', style=ColorStyle.MUTED),
            Text(f'Total input tokens:  {self.total_input_tokens:<10}', style=ColorStyle.MUTED),
            Text(f'Total output tokens: {self.total_output_tokens:<10}', style=ColorStyle.MUTED),
        )
