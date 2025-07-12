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
    thinking_content: str = ''
    thinking_signature: str = ''
    finish_reason: Literal['stop', 'length', 'tool_calls', 'content_filter', 'function_call'] = 'stop'
    usage: Optional[CompletionUsage] = None

    _openai_cache: Optional[dict] = None
    _anthropic_cache: Optional[dict] = None

    def get_content(self):
        """
        only used for token calculation
        """
        if self._content_cache is not None:
            return self._content_cache

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
                content.append(
                    {
                        'type': 'text',
                        'text': tc.tool_args,
                    }
                )

        self._content_cache = content
        return content

    def to_openai(self) -> ChatCompletionMessageParam:
        if self._openai_cache is not None:
            return self._openai_cache

        result = {'role': 'assistant', 'content': self.content}
        if self.tool_calls:
            result['tool_calls'] = [tc.to_openai() for tc in self.tool_calls.values()]

        self._openai_cache = result
        return result

    def to_anthropic(self) -> MessageParam:
        if self._anthropic_cache is not None:
            return self._anthropic_cache

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

        result = MessageParam(
            role='assistant',
            content=content,
        )
        self._anthropic_cache = result
        return result

    def __rich_console__(self, console, options):
        yield from self.get_thinking_renderable()
        yield from self.get_content_renderable()

    def get_thinking_renderable(self):
        if self.thinking_content:
            yield render_message(
                Text('Thinking...', style=ColorStyle.AI_THINKING.italic),
                mark='✻',
                mark_style=ColorStyle.AI_THINKING,
            )
            yield ''
            yield render_message(Text(self.thinking_content, style=ColorStyle.AI_THINKING.italic), mark='')
            yield ''

    def get_content_renderable(self):
        if self.content:
            yield render_message(render_markdown(self.content, style=ColorStyle.AI_CONTENT), mark_style=ColorStyle.AI_MARK)

    def __bool__(self):
        has_content = (self.content is not None) and len(self.content.strip()) > 0
        has_thinking = (self.thinking_content is not None) and len(self.thinking_content.strip()) > 0
        has_tool_calls = (self.tool_calls is not None) and len(self.tool_calls) > 0
        return not self.removed and (has_content or has_thinking or has_tool_calls)

    def merge(self, other: 'AIMessage') -> 'AIMessage':
        """
        # For message continuation, not currently used
        """
        self.content += other.content
        self.finish_reason = other.finish_reason
        self.thinking_content += other.thinking_content
        self.thinking_signature += other.thinking_signature
        if self.usage and other.usage:
            self.usage.completion_tokens += other.usage.completion_tokens
            self.usage.prompt_tokens += other.usage.prompt_tokens
            self.usage.total_tokens += other.usage.total_tokens
        self.tool_calls.update(other.tool_calls)
        self._invalidate_cache()
        return self

    def _invalidate_cache(self):
        """Invalidate all caches when message is modified"""
        super()._invalidate_cache()
        self._openai_cache = None
        self._anthropic_cache = None


class AgentUsage(BaseModel):
    total_llm_calls: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0

    def update(self, ai_message: AIMessage):
        self.total_llm_calls += 1
        if ai_message.usage:
            self.total_input_tokens += ai_message.usage.prompt_tokens
            self.total_output_tokens += ai_message.usage.completion_tokens

    def update_with_usage(self, other_usage: 'AgentUsage'):
        self.total_llm_calls += other_usage.total_llm_calls
        self.total_input_tokens += other_usage.total_input_tokens
        self.total_output_tokens += other_usage.total_output_tokens

    def __rich_console__(self, console, options):
        from rich.console import Group

        yield Group(
            Text(f'Total LLM calls:     {self.total_llm_calls:<10}', style=ColorStyle.HINT),
            Text(f'Total input tokens:  {self.total_input_tokens:<10}', style=ColorStyle.HINT),
            Text(f'Total output tokens: {self.total_output_tokens:<10}', style=ColorStyle.HINT),
        )
