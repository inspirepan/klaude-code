from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, Field
from rich.text import Text

from ..message import ToolCall, ToolMessage, register_tool_call_renderer, register_tool_result_renderer
from ..prompt.tools import GLOB_TOOL_DESC
from ..tool import Tool, ToolInstance
from ..tui import ColorStyle, render_suffix
from ..utils.file_utils import FileGlob, get_relative_path_for_display

"""
- Advanced glob pattern matching with recursive directory support
- Pattern validation and syntax error prevention
- Intelligent result filtering and path optimization
- Performance-tuned file discovery with smart truncation
"""

DEFAULT_MAX_FILES = 100

GLOB_TRUNCATED_SUGGESTION = '(Results are truncated. Consider using a more specific path or pattern.)'


class GlobTool(Tool):
    name = 'Glob'
    desc = GLOB_TOOL_DESC
    parallelable: bool = True

    class Input(BaseModel):
        pattern: Annotated[str, Field(description='The glob pattern to match files against')]
        path: Annotated[
            str,
            Field(
                description='The directory to search in. If not specified, the current working directory will be used. IMPORTANT: Omit this field to use the default directory. DO NOT enter "undefined" or "null" - simply omit it for the default behavior. Must be a valid directory path if provided.'
            ),
        ] = '.'

    @classmethod
    def invoke(cls, tool_call: ToolCall, instance: 'ToolInstance'):
        args: 'GlobTool.Input' = cls.parse_input_args(tool_call)

        # Validate glob pattern
        error_msg = FileGlob.validate_glob_pattern(args.pattern)
        if error_msg:
            instance.tool_result().set_error_msg(error_msg)
            return

        # Validate path
        if not Path(args.path).exists():
            instance.tool_result().set_error_msg(f"Path '{args.path}' does not exist")
            return

        # Execute search and get results
        try:
            result, file_count, truncated = cls._execute_glob_search(args.pattern, args.path)
            instance.tool_result().set_content(result)
            instance.tool_result().set_extra_data('file_count', file_count)
            instance.tool_result().set_extra_data('truncated', truncated)
        except Exception as e:
            instance.tool_result().set_error_msg(f'Search failed: {str(e)}')

    @classmethod
    def _execute_glob_search(cls, pattern: str, path: str) -> tuple[str, int, bool]:
        """Execute glob search and return formatted results with truncation info"""
        files = FileGlob.search_files(pattern, path)
        if not files:
            return 'No files found matching the pattern', 0, False

        file_count = len(files)
        truncated = False

        if len(files) > DEFAULT_MAX_FILES:
            files = files[:DEFAULT_MAX_FILES]
            truncated = True

        result_lines = files
        if truncated:
            suggestion = cls._get_refinement_suggestion(pattern, path, file_count)
            result_lines.append(GLOB_TRUNCATED_SUGGESTION)
            result_lines.append(suggestion)

        return '\n'.join(result_lines), file_count, truncated

    @classmethod
    def _get_refinement_suggestion(cls, pattern: str, path: str, total_files: int) -> str:
        """Generate suggestion for refining glob pattern"""
        suggestions = []

        if not any(char in pattern for char in ['/', '**/']):
            suggestions.append("Use directory-specific patterns (e.g., 'src/**/*.py')")

        if path == '.':
            suggestions.append('Specify a more specific directory path')

        if pattern == '*':
            suggestions.append("Use more specific file patterns (e.g., '*.py', 'test_*')")

        if '**' not in pattern and '/' not in pattern:
            suggestions.append("Use recursive patterns for subdirectories (e.g., '**/*.js')")

        suggestion_text = 'Consider: ' + ' or '.join(suggestions) if suggestions else 'Use more specific glob patterns'
        return f'(Too many files. {suggestion_text})'


@register_tool_call_renderer(GlobTool.name)
def render_glob_args(tool_call: ToolCall, is_suffix: bool = False):
    pattern = tool_call.tool_args_dict.get('pattern', '')
    path = tool_call.tool_args_dict.get('path', '.')

    # Convert absolute path to relative path, but only if it's not the default '.'
    if path != '.':
        display_path = get_relative_path_for_display(path)
        path_info = f' in {display_path}'
    else:
        path_info = ''

    tool_call_msg = Text.assemble(
        ('Glob', ColorStyle.TOOL_NAME.bold if not is_suffix else ColorStyle.MAIN.bold),
        '(',
        (pattern, ColorStyle.INLINE_CODE),
        path_info,
        ')',
    )
    yield tool_call_msg


@register_tool_result_renderer(GlobTool.name)
def render_glob_content(tool_msg: ToolMessage):
    file_count = tool_msg.get_extra_data('file_count', 0)
    truncated = tool_msg.get_extra_data('truncated', False)

    count_text = Text()
    count_text.append('Found ')
    count_text.append(str(file_count), style=ColorStyle.MAIN.bold)
    count_text.append(' files')

    if truncated:
        count_text.append(f' (truncated to {DEFAULT_MAX_FILES} files)', style=ColorStyle.WARNING)

    yield render_suffix(count_text)
