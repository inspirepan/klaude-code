from typing import Annotated

from pydantic import BaseModel, Field
from rich.text import Text

from ..message import ToolCall, ToolMessage, register_tool_call_renderer, register_tool_result_renderer
from ..prompt.tools import EDIT_TOOL_DESC
from ..tool import Tool, ToolInstance
from ..tui import ColorStyle, render_suffix
from ..utils.file_utils import (
    EDIT_OLD_STRING_NEW_STRING_IDENTICAL_ERROR_MSG,
    cleanup_backup,
    count_occurrences,
    create_backup,
    generate_diff_lines,
    generate_snippet_from_diff,
    get_relative_path_for_display,
    read_file_content,
    render_diff_lines,
    replace_string_in_content,
    restore_backup,
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
            instance.parent_agent.session.file_tracker.remove(args.file_path)
            instance.tool_result().set_error_msg(error_msg)
            return

        # Validate file tracking (must be read first)
        is_valid, error_msg = instance.parent_agent.session.file_tracker.validate_track(args.file_path)
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
            instance.parent_agent.session.file_tracker.track(args.file_path)

            # Generate diff and snippet
            diff_lines = generate_diff_lines(content, new_content)
            snippet = generate_snippet_from_diff(diff_lines)

            result = f"The file {args.file_path} has been updated. Here's the result of running `line-number→line-content` on a snippet of the edited file:\n{snippet}"

            instance.tool_result().set_content(result)
            instance.tool_result().set_extra_data('diff_lines', diff_lines)

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

            instance.tool_result().set_error_msg(f'Failed to edit file: {str(e)}')


def render_edit_args(tool_call: ToolCall, is_suffix: bool = False):
    file_path = tool_call.tool_args_dict.get('file_path', '')

    # Convert absolute path to relative path
    display_path = get_relative_path_for_display(file_path)

    tool_call_msg = Text.assemble(
        ('Update', ColorStyle.HIGHLIGHT.bold() if not is_suffix else 'bold'),
        '(',
        display_path,
        ')',
    )
    yield tool_call_msg


def render_edit_result(tool_msg: ToolMessage):
    diff_lines = tool_msg.get_extra_data('diff_lines')
    if diff_lines:
        yield render_suffix(render_diff_lines(diff_lines))


register_tool_call_renderer('Edit', render_edit_args)
register_tool_result_renderer('Edit', render_edit_result)
