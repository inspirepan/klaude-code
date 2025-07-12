from typing import Annotated

from pydantic import BaseModel, Field
from rich.text import Text

from ..message import ToolCall, ToolMessage, register_tool_call_renderer, register_tool_result_renderer
from ..prompt.tools import EDIT_TOOL_DESC
from ..tool import Tool, ToolInstance
from ..tui import ColorStyle, DiffRenderer, render_suffix
from ..utils.file_utils import (
    EDIT_OLD_STRING_NEW_STRING_IDENTICAL_ERROR_MSG,
    count_occurrences,
    create_backup,
    generate_diff_lines,
    generate_snippet_from_diff,
    get_relative_path_for_display,
    read_file_content,
    replace_string_in_content,
    restore_backup,
    try_colorblind_compatible_match,
    validate_file_exists,
    write_file_content,
)

"""
- Precise string matching and replacement
- Uniqueness validation and conflict detection
- Real-time diff preview and context display
- Complete backup and recovery mechanism
"""


class EditTool(Tool):
    name = 'Edit'
    desc = EDIT_TOOL_DESC
    parallelable: bool = False

    class Input(BaseModel):
        file_path: Annotated[str, Field(description='The absolute path to the file to modify')]
        old_string: Annotated[str, Field(description='The text to replace')]
        new_string: Annotated[str, Field(description='The text to replace it with (must be different from old_string)')]
        replace_all: Annotated[bool, Field(description='Replace all occurences of old_string (default false)')] = False

    @classmethod
    def invoke(cls, tool_call: ToolCall, instance: 'ToolInstance'):
        args: 'EditTool.Input' = cls.parse_input_args(tool_call)

        # Validate file exists
        is_valid, error_msg = validate_file_exists(args.file_path)
        if not is_valid:
            instance.agent_state.session.file_tracker.remove(args.file_path)
            instance.tool_result().set_error_msg(error_msg)
            return

        # Validate file tracking (must be read first)
        is_valid, error_msg = instance.agent_state.session.file_tracker.validate_track(args.file_path)
        if not is_valid:
            instance.tool_result().set_error_msg(error_msg)
            return

        # Validate input
        if args.old_string == args.new_string:
            instance.tool_result().set_error_msg(EDIT_OLD_STRING_NEW_STRING_IDENTICAL_ERROR_MSG)
            return

        if not args.old_string:
            instance.tool_result().set_error_msg('old_string cannot be empty')
            return

        backup_path = None

        try:
            # Read current content
            content, warning = read_file_content(args.file_path)
            if not content and warning:
                instance.tool_result().set_error_msg(warning)
                return

            # Check if old_string exists in content
            occurrence_count = count_occurrences(content, args.old_string)
            if occurrence_count == 0:
                # Try colorblind compatibility fix
                found_compatible, corrected_string = try_colorblind_compatible_match(content, args.old_string)
                if found_compatible:
                    # Use the corrected string for replacement
                    args.old_string = corrected_string
                    occurrence_count = count_occurrences(content, args.old_string)
                else:
                    instance.tool_result().set_error_msg(f'String to replace not found in file. String:"{args.old_string}"')
                    return

            # Check for uniqueness if not replace_all
            if not args.replace_all and occurrence_count > 1:
                error_msg = (
                    f'Found {occurrence_count} matches of the string to replace, but replace_all is false. '
                    'To replace all occurrences, set replace_all to true. '
                    'To replace only one occurrence, please provide more context to uniquely identify the instance. '
                    f'String: "{args.old_string}"'
                )
                instance.tool_result().set_error_msg(error_msg)
                return

            # Create backup
            backup_path = create_backup(args.file_path)

            # Perform replacement
            new_content, _ = replace_string_in_content(content, args.old_string, args.new_string, args.replace_all)

            # Write new content
            error_msg = write_file_content(args.file_path, new_content)
            if error_msg:
                restore_backup(args.file_path, backup_path)
                backup_path = None
                instance.tool_result().set_error_msg(error_msg)
                return

            # Update tracking
            instance.agent_state.session.file_tracker.track(args.file_path)

            # Record edit history for undo functionality
            if backup_path:
                operation_summary = (
                    f'Replaced "{args.old_string[:50]}{"..." if len(args.old_string) > 50 else ""}" with "{args.new_string[:50]}{"..." if len(args.new_string) > 50 else ""}"'
                )
                instance.agent_state.session.file_tracker.record_edit(args.file_path, backup_path, 'Edit', operation_summary)

            # Generate diff and snippet
            diff_lines = generate_diff_lines(content, new_content)
            snippet = generate_snippet_from_diff(diff_lines)

            result = f"The file {args.file_path} has been updated. Here's the result of running `line-number→line-content` on a snippet of the edited file:\n{snippet}"

            instance.tool_result().set_content(result)
            instance.tool_result().set_extra_data('diff_lines', diff_lines)

            # Don't clean up backup - keep it for undo functionality

        except Exception as e:
            # Restore from backup if something went wrong
            if backup_path:
                try:
                    restore_backup(args.file_path, backup_path)
                except Exception:
                    pass

            instance.tool_result().set_error_msg(f'Failed to edit file: {str(e)}')


@register_tool_call_renderer(EditTool.name)
def render_edit_args(tool_call: ToolCall, is_suffix: bool = False):
    file_path = tool_call.tool_args_dict.get('file_path', '')

    # Convert absolute path to relative path
    display_path = get_relative_path_for_display(file_path)

    tool_call_msg = Text.assemble(
        ('Update', ColorStyle.TOOL_NAME.bold if not is_suffix else ColorStyle.MAIN.bold),
        '(',
        display_path,
        ')',
    )
    yield tool_call_msg


@register_tool_result_renderer(EditTool.name)
def render_edit_result(tool_msg: ToolMessage):
    diff_lines = tool_msg.get_extra_data('diff_lines')
    if diff_lines:
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
