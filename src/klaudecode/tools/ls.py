from typing import Annotated, List

from pydantic import BaseModel, Field
from rich.text import Text

from ..message import ToolCall, ToolMessage, register_tool_call_renderer, register_tool_result_renderer
from ..prompt.tools import LS_TOOL_DESC, LS_TOOL_RESULT_REMINDER
from ..tool import Tool, ToolInstance
from ..tui import ColorStyle, render_suffix
from ..utils.file_utils import get_directory_structure, get_relative_path_for_display

"""
- Hierarchical directory listing with customizable ignore patterns
- Rich tree visualization of file and folder structures
- Path count statistics and size-aware content truncation
- Hidden file filtering and gitignore-style pattern support
"""


class LsTool(Tool):
    name = 'LS'
    desc = LS_TOOL_DESC
    parallelable: bool = True

    class Input(BaseModel):
        path: Annotated[str, Field(description='The absolute path to the directory to list (must be absolute, not relative)')]
        ignore: Annotated[List[str], Field(description='List of glob patterns to ignore')] = []

    @classmethod
    def invoke(cls, tool_call: ToolCall, instance: 'ToolInstance'):
        args: 'LsTool.Input' = cls.parse_input_args(tool_call)

        try:
            full_result, _, path_count = get_directory_structure(args.path, args.ignore, max_chars=40000, show_hidden=False)
            instance.tool_result().set_content(full_result + '\n\n' + LS_TOOL_RESULT_REMINDER)
            instance.tool_result().set_extra_data('path_count', path_count)

        except Exception as e:
            error_msg = f'Error listing directory: {str(e)}'
            instance.tool_result().set_error_msg(error_msg)


@register_tool_call_renderer(LsTool.name)
def render_ls_args(tool_call: ToolCall, is_suffix: bool = False):
    ignores = tool_call.tool_args_dict.get('ignore', [])
    ignore_info = f' (ignore: {", ".join(ignores)})' if ignores else ''

    path = tool_call.tool_args_dict.get('path', '')
    # Convert absolute path to relative path
    display_path = get_relative_path_for_display(path)

    tool_call_msg = Text.assemble(
        ('List', ColorStyle.TOOL_NAME.bold if not is_suffix else ColorStyle.MAIN.bold),
        '(',
        display_path,
        ignore_info,
        ')',
    )
    yield tool_call_msg


@register_tool_result_renderer(LsTool.name)
def render_ls_content(tool_msg: ToolMessage):
    yield render_suffix(
        Text.assemble(
            'Listed ',
            (str(tool_msg.extra_data.get('path_count', 0)), ColorStyle.MAIN.bold),
            ' paths',
        )
    )
