import re
import shutil
import subprocess
from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, Field
from rich.text import Text

from ..message import ToolCall, ToolMessage, register_tool_call_renderer, register_tool_result_renderer
from ..prompt.tools import GREP_TOOL_DESC
from ..tool import Tool, ToolInstance
from ..tui import ColorStyle, render_suffix
from ..utils.file_utils import DEFAULT_IGNORE_PATTERNS, get_relative_path_for_display

"""
- High-performance content search using ripgrep or fallback grep
- Regex pattern validation and syntax error handling
- Smart result truncation with refinement suggestions
- File type filtering and configurable match limits per file
"""

DEFAULT_MAX_MATCHES_PER_FILE = 10
DEFAULT_MAX_RESULTS = 100  # Maximum total results to show
DEFAULT_TIMEOUT = 30


class GrepTool(Tool):
    name = 'Grep'
    desc = GREP_TOOL_DESC
    parallelable: bool = True

    class Input(BaseModel):
        pattern: Annotated[str, Field(description='The regular expression pattern to search for in file contents')]
        path: Annotated[str, Field(description='The directory to search in. Defaults to the current working directory.')] = '.'
        include: Annotated[str, Field(description='File pattern to include in the search (e.g. "*.js", "*.{ts,tsx}")')] = ''

    @classmethod
    def invoke(cls, tool_call: ToolCall, instance: 'ToolInstance'):
        args: 'GrepTool.Input' = cls.parse_input_args(tool_call)

        # Validate regex pattern
        error_msg = cls._validate_regex(args.pattern)
        if error_msg:
            instance.tool_result().set_error_msg(error_msg)
            return

        # Validate path
        if not Path(args.path).exists():
            instance.tool_result().set_error_msg(f"Path '{args.path}' does not exist")
            return

        # Execute search and get results
        try:
            result, match_count, truncated = cls._execute_search(args.pattern, args.path, args.include)
            instance.tool_result().set_content(result)
            instance.tool_result().set_extra_data('match_count', match_count)
            instance.tool_result().set_extra_data('truncated', truncated)
        except Exception as e:
            instance.tool_result().set_error_msg(f'Search failed: {str(e)}')

    @classmethod
    def _validate_regex(cls, pattern: str) -> str:
        """Validate regex pattern and return error message if invalid"""
        try:
            re.compile(pattern)
            return ''
        except re.error as e:
            return f'Invalid regex pattern: {str(e)}'

    @classmethod
    def _has_ripgrep(cls) -> bool:
        """Check if ripgrep (rg) is available on the system"""
        return shutil.which('rg') is not None

    @classmethod
    def _build_ripgrep_command(cls, pattern: str, path: str, include_pattern: str = '') -> list[str]:
        """Build ripgrep command with optimized arguments"""
        args = [
            'rg',
            '--line-number',  # Show line numbers
            '--with-filename',  # Show filenames
            '--no-heading',  # Don't group by file
            '--sort=path',  # Sort by path for consistent output
            '--color=never',  # No color output
            f'--max-count={DEFAULT_MAX_MATCHES_PER_FILE}',  # Limit matches per file
            '--max-filesize=10M',  # Skip very large files
        ]

        # Add include pattern if specified
        if include_pattern:
            args.extend(['--glob', include_pattern])

        # Add ignore patterns
        for pattern_ignore in DEFAULT_IGNORE_PATTERNS:
            args.extend(['--glob', f'!{pattern_ignore}'])

        # Add regex and path
        args.extend(['-e', pattern, path])

        return args

    @classmethod
    def _build_grep_command(cls, pattern: str, path: str, include_pattern: str = '') -> list[str]:
        """Build standard grep command as fallback"""
        args = ['grep', '-rn']  # recursive, line numbers

        # Add include pattern using find if specified
        if include_pattern:
            args.extend(['--include', include_pattern])

        args.extend([pattern, path])

        return args

    @classmethod
    def _execute_search_command(cls, command: list[str]) -> tuple[str, str, int]:
        """Execute search command and return stdout, stderr, and return code"""
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=DEFAULT_TIMEOUT, cwd=Path.cwd())
            return result.stdout, result.stderr, result.returncode
        except subprocess.TimeoutExpired:
            return '', f'Search timed out after {DEFAULT_TIMEOUT} seconds', 1
        except Exception as e:
            return '', f'Command execution failed: {str(e)}', 1

    @classmethod
    def _execute_search(cls, pattern: str, path: str, include_pattern: str = '') -> tuple[str, int, bool]:
        """Execute search and return formatted results with truncation info"""
        # Choose search tool
        use_ripgrep = cls._has_ripgrep()

        # Build command
        if use_ripgrep:
            command = cls._build_ripgrep_command(pattern, path, include_pattern)
        else:
            command = cls._build_grep_command(pattern, path, include_pattern)

        # Execute search
        stdout, stderr, return_code = cls._execute_search_command(command)

        # Handle errors
        if return_code != 0 and not stdout:
            if 'No such file or directory' in stderr:
                return 'Error: Search path not found or inaccessible', 0, False
            elif 'timed out' in stderr:
                return f'Error: {stderr}', 0, False
            elif stderr.strip():
                return f'Search completed with warnings:\n{stderr.strip()}', 0, False
            else:
                return 'No matches found', 0, False

        # Process results
        if not stdout.strip():
            return 'No matches found', 0, False

        # Parse output to extract filename:line_number
        results = []
        for line in stdout.strip().split('\n'):
            if not line.strip():
                continue

            # Parse format: filename:line_number:content
            parts = line.split(':', 2)
            if len(parts) >= 2:
                filename = parts[0]
                try:
                    line_number = int(parts[1])
                    results.append(f'{filename}:{line_number}')
                except ValueError:
                    # Skip lines that don't match expected format
                    continue

        if not results:
            return 'No matches found', 0, False

        match_count = len(results)
        truncated = False

        # Apply truncation if needed
        if len(results) > DEFAULT_MAX_RESULTS:
            results = results[:DEFAULT_MAX_RESULTS]
            truncated = True

        # Build result with truncation message
        result_lines = results
        if truncated:
            suggestion = cls._get_refinement_suggestion(pattern, path, include_pattern, match_count)
            result_lines.append(f'... (showing first {DEFAULT_MAX_RESULTS} of {match_count} matches)')
            result_lines.append(suggestion)

        return '\n'.join(result_lines), match_count, truncated

    @classmethod
    def _get_refinement_suggestion(cls, pattern: str, path: str, include_pattern: str, total_matches: int) -> str:
        """Generate suggestion for refining search pattern"""
        suggestions = []

        if not include_pattern:
            suggestions.append("Use 'include' parameter to filter file types (e.g., include='*.py')")

        if path == '.':
            suggestions.append('Specify a more specific path to narrow down results')

        if not any(char in pattern for char in ['^', '$', '\\b']):
            suggestions.append('Use more specific regex patterns (e.g., word boundaries \\b)')

        suggestion_text = 'Consider: ' + ' or '.join(suggestions) if suggestions else 'Use more specific search patterns'
        return f'Too many results ({total_matches} total). {suggestion_text}'


@register_tool_call_renderer(GrepTool.name)
def render_grep_args(tool_call: ToolCall, is_suffix: bool = False):
    pattern = tool_call.tool_args_dict.get('pattern', '')
    path = tool_call.tool_args_dict.get('path', '.')
    include = tool_call.tool_args_dict.get('include', '')

    include_info = f' include={include}' if include else ''

    # Convert absolute path to relative path, but only if it's not the default '.'
    if path != '.':
        display_path = get_relative_path_for_display(path)
        path_info = f' in {display_path}'
    else:
        path_info = ''

    tool_call_msg = Text.assemble(
        ('Grep', ColorStyle.TOOL_NAME.bold if not is_suffix else ColorStyle.MAIN.bold),
        '(',
        (pattern, ColorStyle.INLINE_CODE),
        path_info,
        include_info,
        ')',
    )
    yield tool_call_msg


@register_tool_result_renderer(GrepTool.name)
def render_grep_content(tool_msg: ToolMessage):
    match_count = tool_msg.get_extra_data('match_count', 0)
    truncated = tool_msg.get_extra_data('truncated', False)

    count_text = Text()
    count_text.append('Found ')
    count_text.append(str(match_count), style=ColorStyle.MAIN.bold)
    count_text.append(' matches')

    if truncated:
        count_text.append(f' (truncated to {DEFAULT_MAX_RESULTS} matches)', style=ColorStyle.WARNING)

    yield render_suffix(count_text)
