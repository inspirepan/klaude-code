from typing import Annotated, Optional

from pydantic import BaseModel, Field
from rich.text import Text

from ..message import ToolCall, register_tool_call_renderer
from ..tool import Tool, ToolInstance
from .file_utils import cache_file_content, format_with_line_numbers, read_file_content, truncate_content, validate_file_exists

"""
- Flexible reading with offset and line limit support
- Automatic line number formatting display
- Content truncation mechanism to prevent excessive output
- File caching mechanism for subsequent edit validation
- UTF-8 encoding support and empty file handling
"""


class ReadTool(Tool):
    name = 'Read'
    desc = 'Read file content with line numbers and optional offset/limit'

    class Input(BaseModel):
        file_path: Annotated[str, Field(description='The absolute path to the file to read')]
        offset: Annotated[Optional[int], Field(description='The line number to start reading from (1-based)')] = None
        limit: Annotated[Optional[int], Field(description='The number of lines to read')] = None

        def __str__(self):
            parts = [f'Reading {self.file_path}']
            if self.offset is not None:
                parts.append(f'from line {self.offset}')
            if self.limit is not None:
                parts.append(f'({self.limit} lines)')
            return ' '.join(parts)

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
            instance.tool_result().set_content('Empty File')
            return

        # Split content into lines for offset/limit processing
        lines = content.splitlines()
        total_lines = len(lines)

        # Apply offset and limit
        start_line = 1
        if args.offset is not None:
            if args.offset < 1:
                instance.tool_result().set_error_msg('Offset must be >= 1')
                return
            if args.offset > total_lines:
                instance.tool_result().set_error_msg(f'Offset {args.offset} exceeds file length ({total_lines} lines)')
                return
            start_line = args.offset
            lines = lines[args.offset - 1 :]

        if args.limit is not None:
            if args.limit < 1:
                instance.tool_result().set_error_msg('Limit must be >= 1')
                return
            lines = lines[: args.limit]

        # Reconstruct content from selected lines
        selected_content = '\n'.join(lines)

        # Format with line numbers
        formatted_content = format_with_line_numbers(selected_content, start_line)

        # Truncate if necessary
        final_content, was_truncated = truncate_content(formatted_content)

        # Add metadata information
        metadata_parts = []
        metadata_parts.append(f'Total {total_lines} lines')

        if was_truncated:
            metadata_parts.append('Content was truncated')

        if warning:
            metadata_parts.append(warning)

        # Set the result
        if metadata_parts:
            result = final_content + '\n' + '\n'.join(metadata_parts)
        else:
            result = final_content

        instance.tool_result().set_content(result)


def render_read_args(tool_call: ToolCall):
    offset = tool_call.tool_args_dict.get('offset', 0)
    limit = tool_call.tool_args_dict.get('limit', 0)
    line_range = ''
    if offset or limit:
        line_range = f' [{offset}-{offset + limit - 1}]'
    tool_call_msg = Text.assemble(
        (tool_call.tool_name, 'bold'),
        '(',
        tool_call.tool_args_dict.get('file_path', ''),
        line_range,
        ')',
    )
    yield tool_call_msg


register_tool_call_renderer('Read', render_read_args)
