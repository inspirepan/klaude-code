from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, Field
from rich.text import Text

from ..message import Attachment, ToolCall, ToolMessage, count_tokens, register_tool_call_renderer, register_tool_result_renderer
from ..prompt.tools import READ_TOOL_DESC, READ_TOOL_EMPTY_REMINDER, READ_TOOL_RESULT_REMINDER
from ..tool import Tool, ToolInstance
from ..tui import ColorStyle, render_grid, render_suffix
from ..utils.file_utils import FileTracker, get_relative_path_for_display, is_image_path, read_file_content, read_file_lines_partial, validate_file_exists
from ..utils.image_utils import execute_read_image
from ..utils.str_utils import normalize_tabs

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
READ_RESULT_BRIEF_LIMIT = 5


class ReadResult(Attachment):
    success: bool = True
    error_msg: str = ''


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


def execute_read(file_path: str, offset: int = 0, limit: int = 0, tracker: FileTracker = None) -> ReadResult:
    result = ReadResult(path=file_path)

    # Validate file exists
    is_valid, error_msg = validate_file_exists(file_path)
    if not is_valid:
        if tracker is not None:
            tracker.remove(file_path)
        result.success = False
        result.error_msg = error_msg
        return result

    # Check if file is an image
    if is_image_path(file_path):
        return execute_read_image(file_path)

    # Check file size limit only when no offset/limit is provided (reading entire file)
    if offset == 0 and limit == 0:
        try:
            file_size = Path(file_path).stat().st_size
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
    if offset > 0 or limit > 0:
        lines, warning = read_file_lines_partial(file_path, offset if offset > 0 else None, limit if limit > 0 else None)
        if not lines and warning:
            result.success = False
            result.error_msg = warning
            return result
        content = '\n'.join(lines)
    else:
        content, warning = read_file_content(file_path)
        if not content and warning:
            result.success = False
            result.error_msg = warning
            return result
        lines = content.splitlines()

    if tracker is not None:
        tracker.track(file_path)

    # Handle empty file
    if not content:
        result.content = READ_TOOL_EMPTY_REMINDER
        return result

    # Build list of (line_number, content) tuples
    if offset > 0 or limit > 0:
        # For partial reads, we already have the lines we need
        start_line_num = offset if offset > 0 else 1
        numbered_lines = [(start_line_num + i, line) for i, line in enumerate(lines)]
    else:
        # For full file reads, handle offset/limit on the loaded content
        numbered_lines = [(i + 1, line) for i, line in enumerate(lines)]
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
            result.actual_range_str = f'{start_line}-{actual_end_line}'
        else:
            result.actual_range_str = f'{start_line}-{end_line}'

    formatted_content = ''
    formatted_content = '\n'.join([f'{line_num}→{line_content}' for line_num, line_content in truncated_numbered_lines])
    if remaining_line_count > 0:
        formatted_content += f'\n... (more {remaining_line_count} lines are truncated)'
    if warning:
        formatted_content += f'\n{warning}'
    formatted_content += READ_TOOL_RESULT_REMINDER

    result.content = formatted_content
    result.line_count = len(numbered_lines)
    result.brief = truncated_numbered_lines[:READ_RESULT_BRIEF_LIMIT]

    return result


class ReadTool(Tool):
    name = 'Read'
    desc = READ_TOOL_DESC.format(TRUNCATE_LINE_LIMIT=READ_TRUNCATE_LINE_LIMIT, TRUNCATE_LINE_CHAR_LIMIT=READ_TRUNCATE_LINE_CHAR_LIMIT)
    parallelable: bool = True

    class Input(BaseModel):
        file_path: Annotated[str, Field(description='The absolute path to the file to read')]
        offset: Annotated[int, Field(description='The line number to start reading from. Only provide if the file is too large to read at once')] = 0
        limit: Annotated[int, Field(description='The number of lines to read. Only provide if the file is too large to read at once.')] = 0

    @classmethod
    def invoke(cls, tool_call: ToolCall, instance: 'ToolInstance'):
        args: 'ReadTool.Input' = cls.parse_input_args(tool_call)

        result = execute_read(args.file_path, args.offset, args.limit, instance.agent_state.session.file_tracker)

        if not result.success:
            instance.tool_result().set_error_msg(result.error_msg)
            return

        # Check if this is an image file
        if result.type == 'image':
            instance.tool_result().append_attachment(result)
            # Set content to indicate image was read
            instance.tool_result().set_content(f'Successfully read image file: {args.file_path}')
        else:
            # Regular text file handling
            instance.tool_result().set_content(result.content)
            instance.tool_result().set_extra_data('read_line_count', result.line_count)
            instance.tool_result().set_extra_data('brief', result.brief)
            instance.tool_result().set_extra_data('actual_range', result.actual_range_str)
            instance.tool_result().set_extra_data('truncated', result.truncated)


@register_tool_call_renderer(ReadTool.name)
def render_read_args(tool_call: ToolCall, is_suffix: bool = False):
    offset = tool_call.tool_args_dict.get('offset', 0)
    limit = tool_call.tool_args_dict.get('limit', 0)
    line_range = ''
    if offset > 0 and limit > 0:
        line_range = f' {offset}-{offset + limit - 1}'
    elif offset > 0:
        line_range = f' {offset}-'
    elif limit > 0:
        line_range = f' 1-{limit}'

    # Convert absolute path to relative path
    file_path = tool_call.tool_args_dict.get('file_path', '')
    display_path = get_relative_path_for_display(file_path)

    tool_call_msg = Text.assemble(
        (tool_call.tool_name, ColorStyle.TOOL_NAME.bold if not is_suffix else ColorStyle.MAIN.bold),
        '(',
        display_path,
        line_range,
        ')',
    )
    yield tool_call_msg


@register_tool_result_renderer(ReadTool.name)
def render_read_content(tool_msg: ToolMessage):
    if tool_msg.attachments and tool_msg.attachments[0].type == 'image':
        # For images, show file size
        file_size_str = tool_msg.attachments[0].size_str
        yield render_suffix(f'Read image ({file_size_str})')
        return

    read_line_count = tool_msg.get_extra_data('read_line_count', 0)
    brief_list = tool_msg.get_extra_data('brief', [])
    actual_range = tool_msg.get_extra_data('actual_range', None)
    truncated = tool_msg.get_extra_data('truncated', False)

    if brief_list:
        width = max(len(str(brief_list[-1][0])) if brief_list else 3, 3)
        table = render_grid([[f'{line_num:>{width}}', Text(normalize_tabs(line_content))] for line_num, line_content in brief_list], padding=(0, 2))
        table.columns[0].justify = 'right'
        # Build read info with Rich Text for styling
        read_text = Text()
        read_text.append('Read ')
        read_text.append(str(read_line_count), style=ColorStyle.MAIN.bold)
        read_text.append(' lines')

        if actual_range and truncated:
            read_text.append(f' (truncated to line {actual_range})', style=ColorStyle.WARNING)

        # Show ellipsis only if we have READ_RESULT_BRIEF_LIMIT or more lines displayed
        ellipsis = '…' if len(brief_list) >= READ_RESULT_BRIEF_LIMIT else ''
        table.add_row(ellipsis, read_text)
        yield render_suffix(table)
    elif tool_msg.tool_call.status == 'success':
        yield render_suffix('(No content)')
