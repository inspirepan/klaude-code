import glob as python_glob
import os
import shutil
import subprocess
from typing import Annotated, Optional

from pydantic import BaseModel, Field
from rich.text import Text

from ..message import ToolCall, ToolMessage, register_tool_call_renderer, register_tool_result_renderer
from ..prompt.tools import GLOB_TOOL_DESC
from ..tool import Tool, ToolInstance
from ..tui import ColorStyle, render_suffix
from ..utils import DEFAULT_IGNORE_PATTERNS

DEFAULT_MAX_DEPTH = 10
DEFAULT_MAX_FILES = 50
DEFAULT_TIMEOUT = 30


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
        error_msg = cls._validate_glob_pattern(args.pattern)
        if error_msg:
            instance.tool_result().set_error_msg(error_msg)
            return

        # Validate path
        if not os.path.exists(args.path):
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
    def _validate_glob_pattern(cls, pattern: str) -> Optional[str]:
        """Validate glob pattern and return error message if invalid"""
        try:
            # Test the pattern with a simple glob operation
            python_glob.glob(pattern, recursive=True)
            return None
        except Exception as e:
            return f'Invalid glob pattern: {str(e)}'

    @classmethod
    def _has_fd(cls) -> bool:
        """Check if fd (find alternative) is available on the system"""
        return shutil.which('fd') is not None

    @classmethod
    def _has_find(cls) -> bool:
        """Check if find command is available on the system"""
        return shutil.which('find') is not None

    @classmethod
    def _build_fd_command(cls, pattern: str, path: str) -> list[str]:
        """Build fd command with optimized arguments"""
        args = ['fd', '--type', 'f', '--glob']  # Only files, use glob patterns

        # Add depth limit
        args.extend(['--max-depth', str(DEFAULT_MAX_DEPTH)])

        # Add ignore patterns
        for ignore_pattern in DEFAULT_IGNORE_PATTERNS:
            args.extend(['--exclude', ignore_pattern])

        # Add pattern and search path (fd uses glob patterns with --glob flag)
        args.extend([pattern, path])

        return args

    @classmethod
    def _build_find_command(cls, pattern: str, path: str) -> list[str]:
        """Build find command as fallback"""
        args = ['find', path, '-type', 'f']  # Only files

        # Add depth limit
        args.extend(['-maxdepth', str(DEFAULT_MAX_DEPTH)])

        # Add name pattern
        args.extend(['-name', pattern])

        # Add ignore patterns
        for ignore_pattern in DEFAULT_IGNORE_PATTERNS:
            if ignore_pattern.startswith('*.'):
                args.extend(['!', '-name', ignore_pattern])
            else:
                args.extend(['!', '-path', f'*/{ignore_pattern}/*'])

        return args

    @classmethod
    def _execute_command(cls, command: list[str]) -> tuple[str, str, int]:
        """Execute command and return stdout, stderr, and return code"""
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=DEFAULT_TIMEOUT, cwd=os.getcwd())
            return result.stdout, result.stderr, result.returncode
        except subprocess.TimeoutExpired:
            return '', f'Search timed out after {DEFAULT_TIMEOUT} seconds', 1
        except Exception as e:
            return '', f'Command execution failed: {str(e)}', 1

    @classmethod
    def _python_glob_search(cls, pattern: str, path: str) -> list[str]:
        """Use Python's glob module as fallback"""
        try:
            # Construct full pattern
            if path != '.':
                full_pattern = os.path.join(path, pattern)
            else:
                full_pattern = pattern

            # Add recursive search if pattern doesn't already include it
            if '**' not in full_pattern and '/' in pattern:
                full_pattern = os.path.join(path, '**', pattern)

            # Get all matches
            matches = python_glob.glob(full_pattern, recursive=True)

            # Filter matches
            filtered_matches = []
            for match in matches:
                try:
                    if not os.path.exists(match) or not os.path.isfile(match):
                        continue

                    # Skip hidden files
                    if os.path.basename(match).startswith('.'):
                        continue

                    # Check ignore patterns
                    should_ignore = False
                    for ignore_pattern in DEFAULT_IGNORE_PATTERNS:
                        if ignore_pattern.startswith('*.'):
                            # File extension pattern
                            if match.endswith(ignore_pattern[1:]):
                                should_ignore = True
                                break
                        else:
                            # Directory pattern
                            if f'/{ignore_pattern}/' in match or match.endswith(f'/{ignore_pattern}'):
                                should_ignore = True
                                break

                    if not should_ignore:
                        filtered_matches.append(match)

                except (OSError, PermissionError):
                    continue

            return sorted(filtered_matches)

        except Exception:
            return []

    @classmethod
    def _execute_glob_search(cls, pattern: str, path: str) -> tuple[str, int, bool]:
        """Execute glob search and return formatted results with truncation info"""
        files = []

        # Try fd first (fastest)
        if cls._has_fd():
            command = cls._build_fd_command(pattern, path)
            stdout, stderr, return_code = cls._execute_command(command)

            if return_code == 0 and stdout.strip():
                files = [line.strip() for line in stdout.strip().split('\n') if line.strip()]

        # Try find command as fallback
        if not files and cls._has_find():
            command = cls._build_find_command(pattern, path)
            stdout, stderr, return_code = cls._execute_command(command)

            if return_code == 0 and stdout.strip():
                files = [line.strip() for line in stdout.strip().split('\n') if line.strip()]

        # Use Python glob as ultimate fallback
        if not files:
            files = cls._python_glob_search(pattern, path)

        # Handle no results
        if not files:
            return 'No files found matching the pattern', 0, False

        # Sort by modification time (as specified in tool description)
        try:
            files.sort(key=lambda f: os.path.getmtime(f), reverse=True)
        except OSError:
            # If we can't get modification time, just use alphabetical sort
            files.sort()

        file_count = len(files)
        truncated = False

        # Apply truncation if needed
        if len(files) > DEFAULT_MAX_FILES:
            files = files[:DEFAULT_MAX_FILES]
            truncated = True

        # Build result with truncation message
        result_lines = files
        if truncated:
            suggestion = cls._get_refinement_suggestion(pattern, path, file_count)
            result_lines.append(f'... (showing first {DEFAULT_MAX_FILES} of {file_count} files)')
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
        return f'Too many files ({total_files} total). {suggestion_text}'


def render_glob_args(tool_call: ToolCall):
    pattern = tool_call.tool_args_dict.get('pattern', '')
    path = tool_call.tool_args_dict.get('path', '.')

    path_info = f' in {path}' if path != '.' else ''

    tool_call_msg = Text.assemble(
        ('Glob', 'bold'),
        '(',
        (pattern, ColorStyle.INLINE_CODE.value),
        path_info,
        ')',
    )
    yield tool_call_msg


def render_glob_content(tool_msg: ToolMessage):
    file_count = tool_msg.get_extra_data('file_count', 0)
    truncated = tool_msg.get_extra_data('truncated', False)

    count_text = Text()
    count_text.append('Found ')
    count_text.append(str(file_count), style='bold')
    count_text.append(' files')

    if truncated:
        count_text.append(f' (truncated to {DEFAULT_MAX_FILES} files)', style=ColorStyle.WARNING.value)

    yield render_suffix(count_text)


register_tool_call_renderer('Glob', render_glob_args)
register_tool_result_renderer('Glob', render_glob_content)
