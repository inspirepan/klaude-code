import json
from functools import cached_property, lru_cache
from typing import Literal

from anthropic.types import ToolUseBlockParam
from pydantic import BaseModel
from rich.text import Text

from ..tui import ColorStyle, render_message
from .base import count_tokens


class ToolCall(BaseModel):
    id: str
    tool_name: str
    tool_args_dict: dict = {}
    status: Literal['processing', 'success', 'error', 'canceled'] = 'processing'

    _tool_args_cache: str = None
    _tokens_cache: int = None
    _openai_cache: dict = None
    _anthropic_cache: dict = None

    @cached_property
    def tool_args(self) -> str:
        if self._tool_args_cache is not None:
            return self._tool_args_cache
        result = json.dumps(self.tool_args_dict, ensure_ascii=False) if self.tool_args_dict else '{}'  # Gemini requires empty json object here
        self._tool_args_cache = result
        return result

    def __init__(self, **data):
        if 'tool_args' in data and not data.get('tool_args_dict'):
            tool_args_str = data.pop('tool_args')
            if tool_args_str:
                try:
                    data['tool_args_dict'] = json.loads(tool_args_str)
                except (json.JSONDecodeError, TypeError):
                    data['tool_args_dict'] = {}
        super().__init__(**data)
        self._invalidate_cache()

    @property
    def tokens(self) -> int:
        if self._tokens_cache is not None:
            return self._tokens_cache
        func_tokens = count_tokens(self.tool_name)
        args_tokens = count_tokens(self.tool_args)
        self._tokens_cache = func_tokens + args_tokens
        return self._tokens_cache

    def to_openai(self):
        if self._openai_cache is not None:
            return self._openai_cache

        result = {
            'id': self.id,
            'type': 'function',
            'function': {
                'name': self.tool_name,
                'arguments': self.tool_args,
            },
        }
        self._openai_cache = result
        return result

    def to_anthropic(self) -> ToolUseBlockParam:
        if self._anthropic_cache is not None:
            return self._anthropic_cache

        result = {
            'id': self.id,
            'type': 'tool_use',
            'name': self.tool_name,
            'input': self.tool_args_dict,
        }
        self._anthropic_cache = result
        return result

    @staticmethod
    @lru_cache(maxsize=256)
    def get_display_tool_name(tool_name: str) -> str:
        if tool_name.startswith('mcp__'):
            return tool_name[5:] + '(MCP)'
        return tool_name

    @staticmethod
    def get_display_tool_args(tool_args_dict: dict) -> Text:
        return Text.from_markup(', '.join([f'[b]{k}[/b]={v}' for k, v in tool_args_dict.items()]))

    def _invalidate_cache(self):
        """Invalidate all caches when tool call data changes"""
        self._tool_args_cache = None
        self._tokens_cache = None
        self._openai_cache = None
        self._anthropic_cache = None

    def __rich_console__(self, console, options):
        from .registry import _TOOL_CALL_RENDERERS

        if self.tool_name in _TOOL_CALL_RENDERERS:
            for i, item in enumerate(_TOOL_CALL_RENDERERS[self.tool_name](self)):
                if i == 0:
                    yield render_message(item, mark_style=ColorStyle.SUCCESS, status=self.status)
                else:
                    yield item
        else:
            tool_name = ToolCall.get_display_tool_name(self.tool_name)
            msg = Text.assemble((tool_name, ColorStyle.HIGHLIGHT.bold), '(', ToolCall.get_display_tool_args(self.tool_args_dict), ')')
            yield render_message(msg, mark_style=ColorStyle.SUCCESS, status=self.status)

    def get_suffix_renderable(self):
        from .registry import _TOOL_CALL_RENDERERS

        if self.tool_name in _TOOL_CALL_RENDERERS:
            yield from _TOOL_CALL_RENDERERS[self.tool_name](self, is_suffix=True)
        else:
            yield Text.assemble((ToolCall.get_display_tool_name(self.tool_name), ColorStyle.MAIN.bold), '(', ToolCall.get_display_tool_args(self.tool_args_dict), ')')
