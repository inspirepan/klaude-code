from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, Field
from rich.text import Text

from ..message import ToolCall, ToolMessage, register_tool_call_renderer, register_tool_result_renderer
from ..prompt.tools import UNDO_EDIT_TOOL_DESC
from ..tool import Tool, ToolInstance
from ..tui import ColorStyle, DiffRenderer, render_suffix
from ..utils.file_utils import generate_diff_lines, generate_snippet_from_diff, get_relative_path_for_display, read_file_content, restore_backup, validate_file_exists


class UndoEditTool(Tool):
    name = 'UndoEdit'
    desc = UNDO_EDIT_TOOL_DESC
    parallelable: bool = False

    class Input(BaseModel):
        file_path: Annotated[str, Field(description='The path to the file whose last edit should be undone')]

    @classmethod
    def invoke(cls, tool_call: ToolCall, instance: 'ToolInstance'):
        args: 'UndoEditTool.Input' = cls.parse_input_args(tool_call)

        # Validate file exists
        is_valid, error_msg = validate_file_exists(args.file_path)
        if not is_valid:
            instance.agent_state.session.file_tracker.remove(args.file_path)
            instance.tool_result().set_error_msg(error_msg)
            return

        # Get the last edit for this file
        last_edit = instance.agent_state.session.file_tracker.get_last_edit(args.file_path)
        if not last_edit:
            instance.tool_result().set_error_msg(f"No edit history found for file '{args.file_path}'")
            return

        # Check if backup file still exists
        if not Path(last_edit.backup_path).exists():
            instance.tool_result().set_error_msg(f"No edit history found for file '{args.file_path}'")
            return

        try:
            # Read current content for diff generation
            current_content, warning = read_file_content(args.file_path)
            if not current_content and warning:
                instance.tool_result().set_error_msg(f'Failed to read current file content: {warning}')
                return

            # Read backup content for diff generation
            backup_content, warning = read_file_content(last_edit.backup_path)
            if not backup_content and warning:
                instance.tool_result().set_error_msg(f'Failed to read backup file content: {warning}')
                return

            # Restore the file from backup
            restore_backup(args.file_path, last_edit.backup_path)

            # Update tracking
            instance.agent_state.session.file_tracker.track(args.file_path)

            # Remove this edit from history since it's been undone
            instance.agent_state.session.file_tracker.edit_history.remove(last_edit)

            # Generate diff and snippet
            diff_lines = generate_diff_lines(current_content, backup_content)
            snippet = generate_snippet_from_diff(diff_lines)

            result = f"The file {args.file_path} has been reverted to its previous state. Here's the result of running `line-number→line-content` on a snippet of the reverted file:\n{snippet}"

            instance.tool_result().set_content(result)
            instance.tool_result().set_extra_data('diff_lines', diff_lines)

        except Exception as e:
            instance.tool_result().set_error_msg(f'Failed to undo edit: {str(e)}')


@register_tool_call_renderer(UndoEditTool.name)
def render_undo_edit_args(tool_call: ToolCall, is_suffix: bool = False):
    file_path = tool_call.tool_args_dict.get('file_path', '')

    # Convert absolute path to relative path
    display_path = get_relative_path_for_display(file_path)

    tool_call_msg = Text.assemble(
        ('Undo', ColorStyle.TOOL_NAME.bold if not is_suffix else ColorStyle.MAIN.bold),
        '(',
        display_path,
        ')',
    )
    yield tool_call_msg


@register_tool_result_renderer(UndoEditTool.name)
def render_undo_edit_result(tool_msg: ToolMessage):
    diff_lines = tool_msg.get_extra_data('diff_lines')
    if diff_lines:
        diff_renderer = DiffRenderer()
        yield render_suffix(diff_renderer.render_diff_lines(diff_lines))
