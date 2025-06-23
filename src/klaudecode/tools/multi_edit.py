from typing import Annotated, List, NamedTuple, Tuple

from pydantic import BaseModel, Field
from rich.text import Text

from ..message import ToolCall, ToolMessage, register_tool_call_renderer, register_tool_result_renderer
from ..prompt.tools import MULTI_EDIT_TOOL_DESC
from ..tool import Tool, ToolInstance
from ..tui import render_suffix
from .file_utils import (
    cache_file_content,
    cleanup_backup,
    count_occurrences,
    create_backup,
    generate_diff_lines,
    get_edit_context_snippet,
    read_file_content,
    render_diff_lines,
    replace_string_in_content,
    restore_backup,
    validate_file_cache,
    validate_file_exists,
    write_file_content,
)


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
            instance.tool_result().set_error_msg(error_msg)
            return

        # Validation 3: Check cached file state
        is_valid, error_msg = validate_file_cache(args.file_path)
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
                instance.tool_result().set_error_msg(f'Edit {i + 1} - old_string and new_string cannot be identical')
                return

            if not edit.old_string.strip():
                instance.tool_result().set_error_msg(f'Edit {i + 1} - old_string cannot be empty')
                return

        # Validation 5: Comprehensive validation of all edits
        validation_result = _validate_all_edits(args.edits, original_content)
        if not validation_result.valid:
            instance.tool_result().set_error_msg(f'{validation_result.error}. No changes were applied to the file.')
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
                    instance.tool_result().set_error_msg(f'Edit {i + 1} failed: {single_validation.error}. All edits have been rolled back.')
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
                instance.tool_result().set_error_msg(f'Failed to write file: {error_msg}. All edits have been rolled back.')
                return

            # Update cache
            cache_file_content(args.file_path, working_content)

            # Generate context snippet for the last edit
            last_edit = args.edits[-1]
            snippet = get_edit_context_snippet(working_content, last_edit.new_string, original_content, last_edit.old_string, 5)

            # Generate diff
            diff_lines = generate_diff_lines(original_content, working_content)

            # AI readable result
            result = f'Applied {len(args.edits)} edits to {args.file_path}:\n'
            for applied_edit in applied_edits:
                result += f'{applied_edit.index}. Replaced "{applied_edit.old_string}" with "{applied_edit.new_string}"\n'

            result += f"\nHere's the result of running `line-number→line-content` on a snippet of the edited file:\n{snippet}"

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
            instance.tool_result().set_error_msg(f'MultiEdit aborted: {str(e)}. All edits have been rolled back.')


def _validate_all_edits(edits: List[EditOperation], original_content: str) -> ValidationResult:
    if len(edits) == 0:
        return ValidationResult(False, 'No edits provided')

    # Detect potential conflicts
    conflicts = _detect_edit_conflicts(edits, original_content)
    if conflicts:
        conflict_descriptions = [conflict.description for conflict in conflicts]
        return ValidationResult(False, 'Edit conflicts detected:\n' + '\n'.join(conflict_descriptions))

    # Simulate all edits to ensure they work
    simulated_content = original_content
    for i, edit in enumerate(edits):
        old_string = edit.old_string
        new_string = edit.new_string
        replace_all = edit.replace_all

        occurrences = count_occurrences(simulated_content, old_string)

        if occurrences == 0:
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


def _detect_edit_conflicts(edits: List[EditOperation], content: str) -> List[EditConflict]:
    conflicts = []

    for i in range(len(edits) - 1):
        for j in range(i + 1, len(edits)):
            edit1 = edits[i]
            edit2 = edits[j]

            old_string1 = edit1.old_string
            new_string1 = edit1.new_string
            old_string2 = edit2.old_string
            new_string2 = edit2.new_string

            # Conflict Type 1: Later edit modifies earlier edit's result
            if new_string1 in old_string2:
                conflicts.append(
                    EditConflict(
                        type='dependency',
                        edits=(i, j),
                        description=f'Edit {j + 1} depends on result of edit {i + 1}',
                    )
                )

            # Conflict Type 2: Overlapping replacements
            if _edits_overlap(edit1, edit2, content):
                conflicts.append(
                    EditConflict(
                        type='overlap',
                        edits=(i, j),
                        description=f'Edits {i + 1} and {j + 1} affect overlapping text',
                    )
                )

            # Conflict Type 3: Same target, different replacements
            if old_string1 == old_string2 and new_string1 != new_string2:
                conflicts.append(
                    EditConflict(
                        type='contradiction',
                        edits=(i, j),
                        description=f'Edits {i + 1} and {j + 1} replace same text differently',
                    )
                )

    return conflicts


def _edits_overlap(edit1: EditOperation, edit2: EditOperation, content: str) -> bool:
    old_string1 = edit1.old_string
    old_string2 = edit2.old_string

    # Find positions of all occurrences
    positions1 = _find_all_positions(content, old_string1)
    positions2 = _find_all_positions(content, old_string2)

    # Check if any positions overlap
    for pos1 in positions1:
        end1 = pos1 + len(old_string1)
        for pos2 in positions2:
            end2 = pos2 + len(old_string2)
            # Check for overlap: pos1 < end2 and pos2 < end1
            if pos1 < end2 and pos2 < end1:
                return True

    return False


def _find_all_positions(content: str, search_string: str) -> List[int]:
    positions = []
    start = 0
    while True:
        pos = content.find(search_string, start)
        if pos == -1:
            break
        positions.append(pos)
        start = pos + 1
    return positions


def render_multi_edit_args(tool_call: ToolCall):
    file_path = tool_call.tool_args_dict.get('file_path', '')
    edits = tool_call.tool_args_dict.get('edits', [])

    tool_call_msg = Text.assemble(
        ('Update', 'bold'),
        '(',
        file_path,
        ' - ',
        (str(len(edits)), 'bold'),
        ' edits',
        ')',
    )
    yield tool_call_msg


def render_multi_edit_result(tool_msg: ToolMessage):
    diff_lines = tool_msg.get_extra_data('diff_lines')
    if diff_lines:
        yield render_suffix(render_diff_lines(diff_lines))


register_tool_call_renderer('MultiEdit', render_multi_edit_args)
register_tool_result_renderer('MultiEdit', render_multi_edit_result)
