from typing import Annotated, Optional

from pydantic import BaseModel, Field
from rich.text import Text

from ..message import ToolCall, ToolMessage, register_tool_call_renderer, register_tool_result_renderer
from ..prompt.tools import LS_TOOL_DESC
from ..tool import Tool, ToolInstance
from ..tui import render_suffix
from ..utils import get_directory_structure


class LsTool(Tool):
    name = 'LS'
    desc = LS_TOOL_DESC

    class Input(BaseModel):
        path: Annotated[str, Field(description='Absolute path to the directory to list')]
        ignore: Annotated[Optional[str], Field(description='glob patterns to ignore (e.g., "*.log, node_modules")')] = None

    @classmethod
    def invoke(cls, tool_call: ToolCall, instance: 'ToolInstance'):
        args: 'LsTool.Input' = cls.parse_input_args(tool_call)

        try:
            ignore_patterns = []
            if args.ignore:
                if ',' in args.ignore:
                    ignore_patterns = [pattern.strip() for pattern in args.ignore.split(',')]
                else:
                    ignore_patterns = [str(args.ignore)]

            full_result, _, path_count = get_directory_structure(args.path, ignore_patterns, max_chars=40000)
            instance.tool_result().set_content(full_result)
            instance.tool_result().set_extra_data('path_count', path_count)

        except Exception as e:
            error_msg = f'Error listing directory: {str(e)}'
            instance.tool_result().set_error_msg(error_msg)


def render_ls_args(tool_call: ToolCall):
    ignore_patterns = tool_call.tool_args_dict.get('ignore', '')
    ignore_info = f' (ignore: {ignore_patterns})' if ignore_patterns else ''
    tool_call_msg = Text.assemble(
        ('List', 'bold'),
        '(',
        tool_call.tool_args_dict.get('path', ''),
        ignore_info,
        ')',
    )
    yield tool_call_msg


def render_ls_content(tool_msg: ToolMessage):
    yield render_suffix(
        Text.assemble(
            'Listed ',
            (str(tool_msg.get_extra_data('path_count', 0)), 'bold'),
            ' paths',
        )
    )


register_tool_call_renderer('LS', render_ls_args)
register_tool_result_renderer('LS', render_ls_content)
