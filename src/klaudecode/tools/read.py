from typing import Annotated, Optional

from pydantic import BaseModel, Field
from rich.table import Table
from rich.text import Text

from ..message import ToolCall, ToolMessage, register_tool_call_renderer, register_tool_result_renderer
from ..prompt.tools import READ_TOOL_DESC
from ..tool import Tool, ToolInstance
from ..tui import render_suffix
from .file_utils import cache_file_content, read_file_content, truncate_content, validate_file_exists

"""
- Flexible reading with offset and line limit support
- Automatic line number formatting display
- Content truncation mechanism to prevent excessive output
- File caching mechanism for subsequent edit validation
- UTF-8 encoding support and empty file handling
"""

TRUNCATE_CHAR_LIMIT = 5000
TRUNCATE_LINE_LIMIT = 1000


class ReadTool(Tool):
    name = 'Read'
    desc = READ_TOOL_DESC.format(TRUNCATE_CHAR_LIMIT=TRUNCATE_CHAR_LIMIT, TRUNCATE_LINE_LIMIT=TRUNCATE_LINE_LIMIT)

    class Input(BaseModel):
        file_path: Annotated[str, Field(description='The absolute path to the file to read')]
        offset: Annotated[Optional[int], Field(description='The line number to start reading from (1-based)')] = None
        limit: Annotated[Optional[int], Field(description='The number of lines to read')] = None

    @classmethod
    def invoke(cls, tool_call: ToolCall, instance: 'ToolInstance'):
        args: 'ReadTool.Input' = cls.parse_input_args(tool_call)

        # Validate file exists
        is_valid, error_msg = validate_file_exists(args.file_path)
        if not is_valid:
            instance.tool_result().set_error_msg(error_msg)
            return

        # Read file content
        content, warning = read_file_content(args.file_path)
        if not content and warning:
            instance.tool_result().set_error_msg(warning)
            return

        # Cache the file content for potential future edits
        cache_file_content(args.file_path, content)

        # Handle empty file
        if not content:
            instance.tool_result().set_content('(No content)\n\nFull 0 lines')
            return

        # Split content into lines for offset/limit processing
        lines = content.splitlines()
        total_lines = len(lines)

        # Build list of (line_number, content) tuples
        numbered_lines = [(i + 1, line) for i, line in enumerate(lines)]

        if args.offset is not None:
            if args.offset < 1:
                instance.tool_result().set_error_msg('Offset must be >= 1')
                return
            if args.offset > total_lines:
                instance.tool_result().set_error_msg(f'Offset {args.offset} exceeds file length ({total_lines} lines)')
                return
            numbered_lines = numbered_lines[args.offset - 1 :]

        if args.limit is not None:
            if args.limit < 1:
                instance.tool_result().set_error_msg('Limit must be >= 1')
                return
            numbered_lines = numbered_lines[: args.limit]

        # Truncate if necessary
        truncated_numbered_lines, remaining_line_count = truncate_content(numbered_lines, TRUNCATE_CHAR_LIMIT)
        result = ''
        if len(truncated_numbered_lines) > 0:
            width = len(str(truncated_numbered_lines[-1][0]))
            result = '\n'.join([f'{line_num:>{width}}: {line_content}' for line_num, line_content in truncated_numbered_lines])
        else:
            # Handle case where single line content exceeds character limit
            result = numbered_lines[0][1][:TRUNCATE_CHAR_LIMIT] + '... (more content is truncated)'
        if remaining_line_count > 0:
            result += f'\n... (more {remaining_line_count} lines are truncated)'
        if warning:
            result += f'\n{warning}'
        result += f'\n\nFull {total_lines} lines'
        instance.tool_result().set_content(result)
        instance.tool_result().set_extra_data('read_line_count', len(numbered_lines))
        instance.tool_result().set_extra_data('brief', truncated_numbered_lines[:5])


def render_read_args(tool_call: ToolCall):
    offset = tool_call.tool_args_dict.get('offset', 0)
    limit = tool_call.tool_args_dict.get('limit', 0)
    line_range = ''
    if offset and limit:
        line_range = f' [{offset}:{offset + limit - 1}]'
    elif offset:
        line_range = f' [{offset}:]'
    tool_call_msg = Text.assemble(
        (tool_call.tool_name, 'bold'),
        '(',
        tool_call.tool_args_dict.get('file_path', ''),
        line_range,
        ')',
    )
    yield tool_call_msg


def render_read_content(tool_msg: ToolMessage):
    read_line_count = tool_msg.get_extra_data('read_line_count', 0)
    brief_list = tool_msg.get_extra_data('brief', [])
    if brief_list:
        table = Table.grid(padding=(0, 1))
        width = len(str(brief_list[-1][0]))
        table.add_column(width=width, justify='right')
        table.add_column(overflow='fold')
        for line_num, line_content in brief_list:
            table.add_row(f'{line_num:>{width}}:', line_content)
        table.add_row('…', f'Read [bold]{read_line_count}[/bold] lines')
        yield render_suffix(table)
        return
    yield render_suffix(f'Read [bold]{read_line_count}[/bold] lines')


register_tool_call_renderer('Read', render_read_args)
register_tool_result_renderer('Read', render_read_content)
