from typing import Annotated, List, NamedTuple, Tuple

from pydantic import BaseModel, Field
from rich.text import Text

from ..message import ToolCall, ToolMessage, register_tool_call_renderer, register_tool_result_renderer
from ..prompt.tools import MULTI_EDIT_TOOL_DESC
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
- Atomic batch editing with sequential operation processing
- Comprehensive validation and conflict detection across edits
- Smart simulation engine for pre-validation of edit sequences
- Complete rollback mechanism with backup and recovery
"""

ERROR_NOT_APPLIED = 'Failed to apply edit.'


class EditOperation(BaseModel):
    old_string: Annotated[str, Field(description='The text to replace')]
    new_string: Annotated[str, Field(description='The text to replace it with')]
    replace_all: Annotated[bool, Field(description='Replace all occurrences (default: false)')] = False


class ValidationResult(NamedTuple):
    valid: bool
    error: str = ''


class EditConflict(NamedTuple):
    type: str
    edits: Tuple[int, int]
    description: str


class AppliedEdit(NamedTuple):
    index: int
    old_string: str
    new_string: str
    replacements: int


class MultiEditTool(Tool):
    name = 'MultiEdit'
    desc = MULTI_EDIT_TOOL_DESC
    parallelable: bool = False

    class Input(BaseModel):
        file_path: Annotated[str, Field(description='The absolute path to the file to modify')]
        edits: Annotated[List[EditOperation], Field(description='Array of edit operations to perform sequentially on the file')]

    @classmethod
    def invoke(cls, tool_call: ToolCall, instance: 'ToolInstance'):
        args: 'MultiEditTool.Input' = cls.parse_input_args(tool_call)

        # Validation 1: Check if edits list is empty
        if not args.edits:
            instance.tool_result().set_error_msg('edits list cannot be empty')
            return

        # Validation 2: File existence check
        is_valid, error_msg = validate_file_exists(args.file_path)
        if not is_valid:
            instance.agent_state.session.file_tracker.remove(args.file_path)
            instance.tool_result().set_error_msg(error_msg)
            return

        # Validation 3: Check tracked file state
        is_valid, error_msg = instance.agent_state.session.file_tracker.validate_track(args.file_path)
        if not is_valid:
            instance.tool_result().set_error_msg(error_msg)
            return

        # Get file content
        original_content, warning = read_file_content(args.file_path)
        if not original_content and warning:
            instance.tool_result().set_error_msg(warning)
            return

        # Validation 4: Validate each edit structure
        for i, edit in enumerate(args.edits):
            if edit.old_string == edit.new_string:
                instance.tool_result().set_error_msg(f'Edit {i + 1} - {EDIT_OLD_STRING_NEW_STRING_IDENTICAL_ERROR_MSG} {ERROR_NOT_APPLIED}')
                return

            if not edit.old_string.strip():
                instance.tool_result().set_error_msg(f'Edit {i + 1} - old_string cannot be empty')
                return

        # Validation 5: Comprehensive validation of all edits
        validation_result = _validate_all_edits(args.edits, original_content)
        if not validation_result.valid:
            instance.tool_result().set_error_msg(f'{validation_result.error} {ERROR_NOT_APPLIED}')
            return

        backup_path = None
        try:
            # Create backup
            backup_path = create_backup(args.file_path)

            # Apply edits sequentially to working copy
            working_content = original_content
            applied_edits = []

            for i, edit in enumerate(args.edits):
                old_string = edit.old_string
                new_string = edit.new_string
                replace_all = edit.replace_all

                # Validate this edit against current working content
                single_validation = _validate_single_edit(edit, working_content, i)
                if not single_validation.valid:
                    if backup_path:
                        restore_backup(args.file_path, backup_path)
                    instance.tool_result().set_error_msg(f'Edit {i + 1} failed: {single_validation.error} {ERROR_NOT_APPLIED}')
                    return

                # Apply edit to working copy
                working_content, replacement_count = replace_string_in_content(working_content, old_string, new_string, replace_all)

                applied_edits.append(
                    AppliedEdit(
                        index=i + 1,
                        old_string=old_string[:50] + ('...' if len(old_string) > 50 else ''),
                        new_string=new_string[:50] + ('...' if len(new_string) > 50 else ''),
                        replacements=replacement_count,
                    )
                )

            # Write new content
            error_msg = write_file_content(args.file_path, working_content)
            if error_msg:
                if backup_path:
                    restore_backup(args.file_path, backup_path)
                instance.tool_result().set_error_msg(f'Failed to write file: {error_msg} {ERROR_NOT_APPLIED}')
                return

            # Update tracking
            instance.agent_state.session.file_tracker.track(args.file_path)

            # Record edit history for undo functionality
            if backup_path:
                operation_summary = f'Applied {len(args.edits)} edits'
                instance.agent_state.session.file_tracker.record_edit(args.file_path, backup_path, 'MultiEdit', operation_summary)

            # Generate diff and snippet
            diff_lines = generate_diff_lines(original_content, working_content)
            snippet = generate_snippet_from_diff(diff_lines)

            # AI readable result
            result = f'Applied {len(args.edits)} edits to {args.file_path}:\n'
            for applied_edit in applied_edits:
                result += f'{applied_edit.index}. Replaced "{applied_edit.old_string}" with "{applied_edit.new_string}"\n'

            result += f"\nHere's the result of running `line-number→line-content` on a snippet of the edited file:\n{snippet}"

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
            instance.tool_result().set_error_msg(f'MultiEdit aborted: {str(e)} {ERROR_NOT_APPLIED}')


def _validate_all_edits(edits: List[EditOperation], original_content: str) -> ValidationResult:
    if len(edits) == 0:
        return ValidationResult(False, 'No edits provided')

    # Simulate all edits to ensure they work
    simulated_content = original_content
    for i, edit in enumerate(edits):
        old_string = edit.old_string
        new_string = edit.new_string
        replace_all = edit.replace_all

        occurrences = count_occurrences(simulated_content, old_string)

        if occurrences == 0:
            # Try colorblind compatibility fix
            found_compatible, corrected_string = try_colorblind_compatible_match(simulated_content, old_string)
            if found_compatible:
                old_string = corrected_string
                edit.old_string = corrected_string  # Update the edit object
                occurrences = count_occurrences(simulated_content, old_string)
            else:
                return ValidationResult(
                    False,
                    f'Edit {i + 1}: old_string not found. Previous edits may have removed it.',
                )
        if not replace_all and occurrences > 1:
            return ValidationResult(
                False,
                f'Edit {i + 1}: Found {occurrences} matches but replace_all is false. Set replace_all to true or provide more context.',
            )

        # Apply to simulation
        simulated_content, _ = replace_string_in_content(simulated_content, old_string, new_string, replace_all)

    return ValidationResult(True)


def _validate_single_edit(edit: EditOperation, content: str, index: int) -> ValidationResult:
    old_string = edit.old_string
    replace_all = edit.replace_all

    occurrences = count_occurrences(content, old_string)

    if occurrences == 0:
        # Try colorblind compatibility fix
        found_compatible, corrected_string = try_colorblind_compatible_match(content, old_string)
        if found_compatible:
            edit.old_string = corrected_string  # Update the edit object
            old_string = corrected_string
            occurrences = count_occurrences(content, old_string)
        else:
            return ValidationResult(
                False,
                'old_string not found in current content (may be due to previous edits)',
            )

    if not replace_all and occurrences > 1:
        return ValidationResult(
            False,
            f'Found {occurrences} matches but replace_all is false',
        )

    return ValidationResult(True)


@register_tool_call_renderer(MultiEditTool.name)
def render_multi_edit_args(tool_call: ToolCall, is_suffix: bool = False):
    file_path = tool_call.tool_args_dict.get('file_path', '')
    edits = tool_call.tool_args_dict.get('edits', [])

    # Convert absolute path to relative path
    display_path = get_relative_path_for_display(file_path)

    tool_call_msg = Text.assemble(
        ('Update', ColorStyle.TOOL_NAME.bold if not is_suffix else ColorStyle.MAIN.bold),
        '(',
        display_path,
        ' - ',
        (str(len(edits)), ColorStyle.MAIN.bold),
        ' edits',
        ')',
    )
    yield tool_call_msg


@register_tool_result_renderer(MultiEditTool.name)
def render_multi_edit_result(tool_msg: ToolMessage):
    diff_lines = tool_msg.get_extra_data('diff_lines')
    if diff_lines:
        # Get file path from tool content
        content = tool_msg.content
        file_path = ''

        if content:
            lines = content.split('\n')
            first_line = lines[0] if lines else ''

            # Extract from content like "Applied 3 edits to /path/to/file:"
            if 'Applied' in first_line and 'edits to' in first_line:
                parts = first_line.split('Applied ')[1].split(' edits to ')
                if len(parts) == 2:
                    file_path = parts[1].rstrip(':')

        diff_renderer = DiffRenderer()
        yield render_suffix(diff_renderer.render_diff_lines(diff_lines, file_path=file_path, show_summary=True))
