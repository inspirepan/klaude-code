from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, Field
from rich.console import Group
from rich.text import Text

from ..message import ToolCall, ToolMessage, register_tool_call_renderer, register_tool_result_renderer
from ..prompt.tools import WRITE_TOOL_DESC
from ..tool import Tool, ToolInstance
from ..tui import ColorStyle, DiffRenderer, render_grid, render_suffix
from ..utils.file_utils import (
    create_backup,
    ensure_directory_exists,
    generate_diff_lines,
    generate_snippet_from_diff,
    get_relative_path_for_display,
    read_file_content,
    restore_backup,
    write_file_content,
)
from ..utils.str_utils import normalize_tabs

"""
- Safety mechanism requiring existing files to be read first
- Automatic directory creation and backup recovery
- File permission preservation and encoding handling
"""

WRITE_RESULT_BRIEF_LIMIT = 5


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
        old_content = ''

        try:
            # If file exists, it must have been read first (safety check)
            if file_exists:
                is_valid, error_msg = instance.agent_state.session.file_tracker.validate_track(args.file_path)
                if not is_valid:
                    instance.tool_result().set_error_msg(error_msg)
                    return

                # Read current content for diff
                old_content, warning = read_file_content(args.file_path)
                if warning:
                    instance.tool_result().set_error_msg(warning)
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
            instance.agent_state.session.file_tracker.track(args.file_path)

            # Record edit history for undo functionality
            if backup_path:
                operation_summary = f'Wrote {len(args.content)} characters to file'
                instance.agent_state.session.file_tracker.record_edit(args.file_path, backup_path, 'Write', operation_summary)

            # Generate diff if file existed
            diff_lines = []
            snippet = ''
            if file_exists and old_content != args.content:
                diff_lines = generate_diff_lines(old_content, args.content)
                snippet = generate_snippet_from_diff(diff_lines)

            # Extract preview lines for display
            lines = args.content.splitlines()
            preview_lines = []
            for i, line in enumerate(lines[:WRITE_RESULT_BRIEF_LIMIT], 1):
                preview_lines.append((i, line))

            if file_exists:
                result = f"The file {args.file_path} has been updated. Here's the result of running `line-number→line-content` on a snippet of the edited file:\n{snippet}"
            else:
                result = f'File created successfully at: {args.file_path}'

            instance.tool_result().set_content(result)
            instance.tool_result().set_extra_data('preview_lines', preview_lines)
            instance.tool_result().set_extra_data('total_lines', len(lines))
            instance.tool_result().set_extra_data('file_exists', file_exists)
            instance.tool_result().set_extra_data('diff_lines', diff_lines)

            # Don't clean up backup - keep it for undo functionality

        except Exception as e:
            # Restore from backup if something went wrong
            if backup_path:
                try:
                    restore_backup(args.file_path, backup_path)
                except Exception:
                    pass

            instance.tool_result().set_error_msg(f'Failed to write file: {str(e)}')


@register_tool_call_renderer(WriteTool.name)
def render_write_args(tool_call: ToolCall, is_suffix: bool = False):
    file_path = tool_call.tool_args_dict.get('file_path', '')

    # Convert absolute path to relative path
    display_path = get_relative_path_for_display(file_path)

    tool_call_msg = Text.assemble(
        (tool_call.tool_name, ColorStyle.TOOL_NAME.bold if not is_suffix else ColorStyle.MAIN.bold),
        '(',
        display_path,
        ')',
    )
    yield tool_call_msg


@register_tool_result_renderer(WriteTool.name)
def render_write_result(tool_msg: ToolMessage):
    if tool_msg.error_msg is not None:
        return
    preview_lines = tool_msg.get_extra_data('preview_lines', [])
    total_lines = tool_msg.get_extra_data('total_lines', 0)
    file_exists = tool_msg.get_extra_data('file_exists', False)
    diff_lines = tool_msg.get_extra_data('diff_lines', [])

    # If this was an overwrite with changes, show diff like Edit tool
    if file_exists and diff_lines:
        # Get file path from tool content
        content = tool_msg.content
        file_path = ''
        if content and 'has been updated' in content:
            # Extract file path from content like "The file /path/to/file has been updated"
            parts = content.split(' has been updated')
            if parts:
                file_part = parts[0].replace('The file ', '')
                file_path = file_part

        diff_renderer = DiffRenderer()
        yield render_suffix(diff_renderer.render_diff_lines(diff_lines, file_path=file_path, show_summary=True))

    # If this was a new file creation, show line count summary and preview
    elif not file_exists:
        # Get file path from tool content for display
        content = tool_msg.content
        file_path = ''
        if content and 'created successfully at:' in content:
            parts = content.split(' at: ')
            if len(parts) == 2:
                file_path = parts[1]

        display_path = get_relative_path_for_display(file_path) if file_path else 'file'

        # Create summary similar to Edit tool
        summary_text = Text.assemble('Wrote ', (str(total_lines), ColorStyle.MAIN.bold), f' line{"s" if total_lines != 1 else ""} to ', (display_path, ColorStyle.MAIN.bold))

        # Show preview if we have lines
        if preview_lines and total_lines > 0:
            width = max(len(str(preview_lines[-1][0])) if preview_lines else 3, 3)
            table = render_grid([[f'{line_num:>{width}}', Text(normalize_tabs(line_content))] for line_num, line_content in preview_lines], padding=(0, 2))
            table.columns[0].justify = 'right'
            if total_lines > len(preview_lines):
                # Build write info with Rich Text for styling similar to Read tool
                write_text = Text()
                write_text.append('Wrote ')
                write_text.append(str(total_lines), style=ColorStyle.MAIN.bold)
                write_text.append(' lines')
                # Show ellipsis only if we have WRITE_RESULT_BRIEF_LIMIT or more lines displayed
                ellipsis = '…' if len(preview_lines) >= WRITE_RESULT_BRIEF_LIMIT else ''
                table.add_row(ellipsis, write_text)

            yield render_suffix(Group(summary_text, table))
        elif total_lines > 0:
            yield render_suffix(summary_text)
        else:
            yield render_suffix(Group(summary_text, Text('(Empty file)')))
