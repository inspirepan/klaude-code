import json
from functools import cached_property
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

    @cached_property
    def tool_args(self) -> str:
        return json.dumps(self.tool_args_dict, ensure_ascii=False) if self.tool_args_dict else ''

    def __init__(self, **data):
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

    @staticmethod
    def get_display_tool_name(tool_name: str) -> str:
        if tool_name.startswith('mcp__'):
            return tool_name[5:] + '(MCP)'
        return tool_name

    @staticmethod
    def get_display_tool_args(tool_args_dict: dict) -> Text:
        return Text.from_markup(', '.join([f'[b]{k}[/b]={v}' for k, v in tool_args_dict.items()]))

    def __rich_console__(self, console, options):
        from .registry import _TOOL_CALL_RENDERERS

        if self.tool_name in _TOOL_CALL_RENDERERS:
            for i, item in enumerate(_TOOL_CALL_RENDERERS[self.tool_name](self)):
                if i == 0:
                    yield render_message(item, mark_style=ColorStyle.SUCCESS.value, status=self.status)
                else:
                    yield item
        else:
            tool_name = ToolCall.get_display_tool_name(self.tool_name)
            msg = Text.assemble((tool_name, ColorStyle.HIGHLIGHT.bold()), '(', ToolCall.get_display_tool_args(self.tool_args_dict), ')')
            yield render_message(msg, mark_style=ColorStyle.SUCCESS.value, status=self.status)

    def get_suffix_renderable(self):
        from .registry import _TOOL_CALL_RENDERERS

        if self.tool_name in _TOOL_CALL_RENDERERS:
            for item in _TOOL_CALL_RENDERERS[self.tool_name](self, is_suffix=True):
                yield item
        else:
            yield Text.assemble((ToolCall.get_display_tool_name(self.tool_name), 'bold'), '(', ToolCall.get_display_tool_args(self.tool_args_dict), ')')
