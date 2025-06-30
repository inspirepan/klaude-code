from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, Field
from rich.text import Text

from ..message import ToolCall, ToolMessage, register_tool_call_renderer, register_tool_result_renderer
from ..prompt.tools import WRITE_TOOL_DESC
from ..tool import Tool, ToolInstance
from ..tui import ColorStyle, render_grid, render_suffix
from ..utils.file_utils import cleanup_backup, create_backup, ensure_directory_exists, get_relative_path_for_display, restore_backup, write_file_content
from ..utils.str_utils import normalize_tabs

"""
- Safety mechanism requiring existing files to be read first
- Automatic directory creation and backup recovery
- File permission preservation and encoding handling
"""


class WriteTool(Tool):
    name = 'Write'
    desc = WRITE_TOOL_DESC
    parallelable: bool = False

    class Input(BaseModel):
        file_path: Annotated[str, Field(description='The absolute path to the file to write (must be absolute, not relative)')]
        content: Annotated[str, Field(description='The content to write to the file')]

    @classmethod
    def invoke(cls, tool_call: ToolCall, instance: 'ToolInstance'):
        args: 'WriteTool.Input' = cls.parse_input_args(tool_call)

        file_exists = Path(args.file_path).exists()
        backup_path = None

        try:
            # If file exists, it must have been read first (safety check)
            if file_exists:
                is_valid, error_msg = instance.parent_agent.session.file_tracker.validate_track(args.file_path)
                if not is_valid:
                    instance.tool_result().set_error_msg(error_msg)
                    return

                # Create backup before writing
                backup_path = create_backup(args.file_path)

            else:
                # For new files, ensure directory exists
                ensure_directory_exists(args.file_path)

            # Write the content
            error_msg = write_file_content(args.file_path, args.content)
            if error_msg:
                # Restore from backup if write failed
                if backup_path:
                    try:
                        restore_backup(args.file_path, backup_path)
                        backup_path = None  # Don't cleanup since we restored
                    except Exception:
                        pass
                instance.tool_result().set_error_msg(error_msg)
                return

            # Update tracking with new content
            instance.parent_agent.session.file_tracker.track(args.file_path)

            # Extract preview lines for display
            lines = args.content.splitlines()
            preview_lines = []
            for i, line in enumerate(lines[:5], 1):
                preview_lines.append((i, line))

            if file_exists:
                result = f'File updated successfully at: {args.file_path}'
            else:
                result = f'File created successfully at: {args.file_path}'

            instance.tool_result().set_content(result)
            instance.tool_result().set_extra_data('preview_lines', preview_lines)
            instance.tool_result().set_extra_data('total_lines', len(lines))

            # Clean up backup on success
            if backup_path:
                cleanup_backup(backup_path)

        except Exception as e:
            # Restore from backup if something went wrong
            if backup_path:
                try:
                    restore_backup(args.file_path, backup_path)
                except Exception:
                    pass

            instance.tool_result().set_error_msg(f'Failed to write file: {str(e)}')


def render_write_args(tool_call: ToolCall, is_suffix: bool = False):
    file_path = tool_call.tool_args_dict.get('file_path', '')

    # Convert absolute path to relative path
    display_path = get_relative_path_for_display(file_path)

    tool_call_msg = Text.assemble(
        (tool_call.tool_name, ColorStyle.HIGHLIGHT.bold() if not is_suffix else 'bold'),
        '(',
        display_path,
        ')',
    )
    yield tool_call_msg


def render_write_result(tool_msg: ToolMessage):
    preview_lines = tool_msg.get_extra_data('preview_lines', [])
    total_lines = tool_msg.get_extra_data('total_lines', 0)

    if preview_lines:
        width = max(len(str(preview_lines[-1][0])) if preview_lines else 3, 3)
        table = render_grid([[f'{line_num:>{width}}', Text(normalize_tabs(line_content))] for line_num, line_content in preview_lines], padding=(0, 2))
        table.columns[0].justify = 'right'
        table.add_row('…' if total_lines > len(preview_lines) else '', f'Written [bold]{total_lines}[/bold] lines')

        yield render_suffix(table)
    elif total_lines > 0:
        yield render_suffix(f'Written [bold]{total_lines}[/bold] lines')
    elif tool_msg.tool_call.status == 'success':
        yield render_suffix('(Empty file)')


register_tool_call_renderer('Write', render_write_args)
register_tool_result_renderer('Write', render_write_result)
