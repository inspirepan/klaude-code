from typing import Annotated, Optional

from pydantic import BaseModel, Field
from rich.markup import escape
from rich.table import Table
from rich.text import Text

from ..message import ToolCall, ToolMessage, register_tool_call_renderer, register_tool_result_renderer
from ..prompt.tools import READ_TOOL_DESC, READ_TOOL_EMPTY_REMINDER, READ_TOOL_RESULT_REMINDER
from ..tool import Tool, ToolInstance
from ..tui import ColorStyle, render_suffix
from .file_utils import cache_file_content, read_file_content, truncate_content, validate_file_exists

"""
- Flexible reading with offset and line limit support
- Automatic line number formatting display
- Content truncation mechanism to prevent excessive output
- File caching mechanism for subsequent edit validation
- UTF-8 encoding support and empty file handling
"""

READ_TRUNCATE_CHAR_LIMIT = 40000
READ_TRUNCATE_LINE_CHAR_LIMIT = 2000
READ_TRUNCATE_LINE_LIMIT = 2000


class ReadResult:
    def __init__(self):
        self.success = True
        self.error_msg = None
        self.content = None
        self.read_line_count = 0
        self.brief = []
        self.actual_range = None
        self.truncated = False


def execute_read(file_path: str, offset: Optional[int] = None, limit: Optional[int] = None) -> ReadResult:
    result = ReadResult()

    # Validate file exists
    is_valid, error_msg = validate_file_exists(file_path)
    if not is_valid:
        result.success = False
        result.error_msg = error_msg
        return result

    # Read file content
    content, warning = read_file_content(file_path)
    if not content and warning:
        result.success = False
        result.error_msg = warning
        return result

    # Cache the file content for potential future edits
    cache_file_content(file_path, content)

    # Handle empty file
    if not content:
        result.content = READ_TOOL_EMPTY_REMINDER
        return result

    # Split content into lines for offset/limit processing
    lines = content.splitlines()
    total_lines = len(lines)

    # Build list of (line_number, content) tuples
    numbered_lines = [(i + 1, line) for i, line in enumerate(lines)]

    if offset is not None:
        if offset < 1:
            result.success = False
            result.error_msg = 'Offset must be >= 1'
            return result
        if offset > total_lines:
            result.success = False
            result.error_msg = f'Offset {offset} exceeds file length ({total_lines} lines)'
            return result
        numbered_lines = numbered_lines[offset - 1 :]

    if limit is not None:
        if limit < 1:
            result.success = False
            result.error_msg = 'Limit must be >= 1'
            return result
        numbered_lines = numbered_lines[:limit]

    # Truncate if necessary
    truncated_numbered_lines, remaining_line_count = truncate_content(numbered_lines, READ_TRUNCATE_CHAR_LIMIT, READ_TRUNCATE_LINE_LIMIT, READ_TRUNCATE_LINE_CHAR_LIMIT)

    # Check if content was truncated
    result.truncated = remaining_line_count > 0 or len(truncated_numbered_lines) < len(numbered_lines)

    # Calculate actual range that AI will read
    if len(numbered_lines) > 0:
        start_line = numbered_lines[0][0]
        end_line = numbered_lines[-1][0]
        if len(truncated_numbered_lines) > 0:
            # If truncated, show range of what's actually shown
            actual_end_line = truncated_numbered_lines[-1][0]
            result.actual_range = f'{start_line}:{actual_end_line}'
        else:
            result.actual_range = f'{start_line}:{end_line}'

    formatted_content = ''
    formatted_content = '\n'.join([f'{line_num}→{line_content}' for line_num, line_content in truncated_numbered_lines])
    if remaining_line_count > 0:
        formatted_content += f'\n... (more {remaining_line_count} lines are truncated)'
    if warning:
        formatted_content += f'\n{warning}'
    formatted_content += READ_TOOL_RESULT_REMINDER
    formatted_content += f'\n\nFull {total_lines} lines'

    result.content = formatted_content
    result.read_line_count = len(numbered_lines)
    result.brief = truncated_numbered_lines[:5]

    return result


class ReadTool(Tool):
    name = 'Read'
    desc = READ_TOOL_DESC.format(TRUNCATE_LINE_LIMIT=READ_TRUNCATE_LINE_LIMIT, TRUNCATE_LINE_CHAR_LIMIT=READ_TRUNCATE_LINE_CHAR_LIMIT)
    parallelable: bool = True

    class Input(BaseModel):
        file_path: Annotated[str, Field(description='The absolute path to the file to read')]
        offset: Annotated[Optional[int], Field(description='The line number to start reading from. Only provide if the file is too large to read at once')] = None
        limit: Annotated[Optional[int], Field(description='The number of lines to read. Only provide if the file is too large to read at once.')] = None

    @classmethod
    def invoke(cls, tool_call: ToolCall, instance: 'ToolInstance'):
        args: 'ReadTool.Input' = cls.parse_input_args(tool_call)

        result = execute_read(args.file_path, args.offset, args.limit)

        if not result.success:
            instance.tool_result().set_error_msg(result.error_msg)
            return

        instance.tool_result().set_content(result.content)
        instance.tool_result().set_extra_data('read_line_count', result.read_line_count)
        instance.tool_result().set_extra_data('brief', result.brief)
        instance.tool_result().set_extra_data('actual_range', result.actual_range)
        instance.tool_result().set_extra_data('truncated', result.truncated)


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
    actual_range = tool_msg.get_extra_data('actual_range', None)
    truncated = tool_msg.get_extra_data('truncated', False)

    if brief_list:
        table = Table.grid(padding=(0, 1))
        width = len(str(brief_list[-1][0]))
        table.add_column(width=width, justify='right')
        table.add_column(overflow='fold')
        for line_num, line_content in brief_list:
            table.add_row(f'{line_num:>{width}}:', escape(line_content))

        # Build read info with Rich Text for styling
        read_text = Text()
        read_text.append('Read ')
        read_text.append(str(read_line_count), style='bold')
        read_text.append(' lines')

        if actual_range and truncated:
            read_text.append(f' (truncated to line {actual_range})', style=ColorStyle.WARNING.value)

        table.add_row('…', read_text)
        yield render_suffix(table)
    elif tool_msg.tool_call.status == 'success':
        yield render_suffix('(No content)')


register_tool_call_renderer('Read', render_read_args)
register_tool_result_renderer('Read', render_read_content)
