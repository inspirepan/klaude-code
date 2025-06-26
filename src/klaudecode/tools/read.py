import os
from typing import Annotated, Optional

from pydantic import BaseModel, Field
from rich.markup import escape
from rich.table import Table
from rich.text import Text

from ..message import ToolCall, ToolMessage, count_tokens, register_tool_call_renderer, register_tool_result_renderer
from ..prompt.tools import READ_TOOL_DESC, READ_TOOL_EMPTY_REMINDER, READ_TOOL_RESULT_REMINDER
from ..tool import Tool, ToolInstance
from ..tui import ColorStyle, render_suffix
from .file_utils import cache_file_content, read_file_content, validate_file_exists

"""
- Flexible reading with offset and line limit support
- Automatic line number formatting display
- Content truncation mechanism to prevent excessive output
- File caching mechanism for subsequent edit validation
- UTF-8 encoding support and empty file handling
"""

READ_TRUNCATE_LINE_CHAR_LIMIT = 2000
READ_TRUNCATE_LINE_LIMIT = 2000
READ_MAX_FILE_SIZE_KB = 256
READ_MAX_TOKENS = 25000
READ_SIZE_LIMIT_ERROR_MSG = 'File content ({size:.1f}KB) exceeds maximum allowed size ({max_size}KB). Please use offset and limit parameters to read specific portions of the file, or use the GrepTool to search for specific content.'
READ_TOKEN_LIMIT_ERROR_MSG = 'File content ({tokens} tokens) exceeds maximum allowed tokens ({max_tokens}). Please use offset and limit parameters to read specific portions of the file, or use the GrepTool to search for specific content.'


class ReadResult:
    def __init__(self):
        self.success = True
        self.error_msg = None
        self.content = None
        self.read_line_count = 0
        self.brief = []
        self.actual_range = None
        self.truncated = False


def truncate_content(numbered_lines, line_limit: int, line_char_limit: int):
    """Truncate content by line limit and line character limit only, no total character limit"""
    if len(numbered_lines) <= line_limit:
        # Apply line character limit only
        truncated_lines = []
        for line_num, line_content in numbered_lines:
            if len(line_content) > line_char_limit:
                processed_line_content = line_content[:line_char_limit] + f'... (more {len(line_content) - line_char_limit} characters in this line are truncated)'
            else:
                processed_line_content = line_content
            truncated_lines.append((line_num, processed_line_content))
        return truncated_lines, 0

    # Apply both line limit and line character limit
    truncated_lines = []
    for i, (line_num, line_content) in enumerate(numbered_lines):
        if i >= line_limit:
            remaining_line_count = len(numbered_lines) - i
            return truncated_lines, remaining_line_count

        if len(line_content) > line_char_limit:
            processed_line_content = line_content[:line_char_limit] + f'... (more {len(line_content) - line_char_limit} characters in this line are truncated)'
        else:
            processed_line_content = line_content

        truncated_lines.append((line_num, processed_line_content))

    return truncated_lines, 0


def read_file_lines_partial(file_path: str, offset: Optional[int] = None, limit: Optional[int] = None) -> tuple[list[str], str]:
    """Read file lines with offset and limit to avoid loading entire file into memory"""
    try:
        lines = []
        warning = ''
        with open(file_path, 'r', encoding='utf-8') as f:
            if offset is not None and offset > 1:
                for _ in range(offset - 1):
                    try:
                        next(f)
                    except StopIteration:
                        break

            count = 0
            max_lines = limit if limit is not None else float('inf')

            for line in f:
                if count >= max_lines:
                    break
                lines.append(line.rstrip('\n\r'))
                count += 1

        return lines, warning
    except UnicodeDecodeError:
        try:
            lines = []
            with open(file_path, 'r', encoding='latin-1') as f:
                if offset is not None and offset > 1:
                    for _ in range(offset - 1):
                        try:
                            next(f)
                        except StopIteration:
                            break

                count = 0
                max_lines = limit if limit is not None else float('inf')

                for line in f:
                    if count >= max_lines:
                        break
                    lines.append(line.rstrip('\n\r'))
                    count += 1

            return lines, '<system-reminder>warning: File decoded using latin-1 encoding</system-reminder>'
        except Exception as e:
            return [], f'Failed to read file: {str(e)}'
    except Exception as e:
        return [], f'Failed to read file: {str(e)}'


def execute_read(file_path: str, offset: Optional[int] = None, limit: Optional[int] = None) -> ReadResult:
    result = ReadResult()

    # Validate file exists
    is_valid, error_msg = validate_file_exists(file_path)
    if not is_valid:
        result.success = False
        result.error_msg = error_msg
        return result

    # Check file size limit only when no offset/limit is provided (reading entire file)
    if offset is None and limit is None:
        try:
            file_size = os.path.getsize(file_path)
            max_size_bytes = READ_MAX_FILE_SIZE_KB * 1024
            if file_size > max_size_bytes:
                result.success = False
                size_kb = file_size / 1024
                result.error_msg = READ_SIZE_LIMIT_ERROR_MSG.format(size=size_kb, max_size=READ_MAX_FILE_SIZE_KB)
                return result
        except OSError as e:
            result.success = False
            result.error_msg = f'Failed to check file size: {str(e)}'
            return result

    # Read file content - use partial reading if offset/limit provided
    if offset is not None or limit is not None:
        lines, warning = read_file_lines_partial(file_path, offset, limit)
        if not lines and warning:
            result.success = False
            result.error_msg = warning
            return result
        content = '\n'.join(lines)
        total_lines = None  # We don't know total lines when reading partially
    else:
        content, warning = read_file_content(file_path)
        if not content and warning:
            result.success = False
            result.error_msg = warning
            return result
        lines = content.splitlines()
        total_lines = len(lines)

    cache_file_content(file_path)

    # Handle empty file
    if not content:
        result.content = READ_TOOL_EMPTY_REMINDER
        return result

    # Build list of (line_number, content) tuples
    if offset is not None or limit is not None:
        # For partial reads, we already have the lines we need
        start_line_num = offset if offset is not None else 1
        numbered_lines = [(start_line_num + i, line) for i, line in enumerate(lines)]
    else:
        # For full file reads, handle offset/limit on the loaded content
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

    # Truncate if necessary (only line limit and line char limit, no total char limit)
    truncated_numbered_lines, remaining_line_count = truncate_content(numbered_lines, READ_TRUNCATE_LINE_LIMIT, READ_TRUNCATE_LINE_CHAR_LIMIT)

    # Check token count limit after truncation
    truncated_content = '\n'.join([line_content for _, line_content in truncated_numbered_lines])
    token_count = count_tokens(truncated_content)
    if token_count > READ_MAX_TOKENS:
        result.success = False
        result.error_msg = READ_TOKEN_LIMIT_ERROR_MSG.format(tokens=token_count, max_tokens=READ_MAX_TOKENS)
        return result

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
