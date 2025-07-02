import shutil
import subprocess

from typing import Callable, Dict, List, Optional

from prompt_toolkit.completion import Completer, Completion

from ..utils.file_utils.directory_utils import get_effective_ignore_patterns
from .input_command import _SLASH_COMMANDS, Command

DEFAULT_MAX_DEPTH = 10


class UserInputCompleter(Completer):
    """Custom user input completer"""

    def __init__(self, enable_file_completion_callabck: Callable[[], bool], enable_command_callabck: Callable[[], bool]):
        self.commands: Dict[str, Command] = _SLASH_COMMANDS
        self.enable_file_completion_callabck = enable_file_completion_callabck
        self.enable_command_callabck = enable_command_callabck
        self._file_cache: Optional[List[str]] = None
        self._initialize_file_cache()
        self._file_cache.sort()
        print('\n'.join(self._file_cache))
        print(len(self._file_cache))

    def get_completions(self, document, _complete_event):
        text = document.text
        cursor_position = document.cursor_position

        at_match = self._find_at_file_pattern(text, cursor_position)
        if at_match and self.enable_file_completion_callabck():
            try:
                yield from self._get_file_completions(at_match)
            except Exception:
                pass
            return

        if not self.enable_command_callabck():
            return

        if not text.startswith('/') or cursor_position == 0:
            return

        command_part = text[1:cursor_position] if cursor_position > 1 else ''

        if ' ' not in command_part:
            for command_name, command in self.commands.items():
                if command_name.startswith(command_part):
                    yield Completion(
                        command_name,
                        start_position=-len(command_part),
                        display=f'/{command_name:15}',
                        display_meta=command.get_command_desc(),
                    )

    def _find_at_file_pattern(self, text, cursor_position):
        for i in range(cursor_position - 1, -1, -1):
            if text[i] == '@':
                file_prefix = text[i + 1 : cursor_position]
                return {'at_position': i, 'prefix': file_prefix, 'start_position': i + 1 - cursor_position}
            elif text[i].isspace():
                break
        return None

    def _initialize_file_cache(self):
        """Initialize file cache using fd or find command"""
        try:
            self._file_cache = self._get_files_from_commands()
        except Exception:
            self._file_cache = []

    def _get_files_from_commands(self) -> List[str]:
        """Get file list using fd or find command"""
        ignore_patterns = get_effective_ignore_patterns()

        files = self._try_fd_command(ignore_patterns)
        if files is not None:
            return files

        return []

    def _try_fd_command(self, ignore_patterns: List[str]) -> Optional[List[str]]:
        """Try using fd command"""
        try:
            if not shutil.which('fd'):
                return None
            args = ['fd', '.']
            args.extend(['-maxdepth', str(DEFAULT_MAX_DEPTH)])
            # Add ignore patterns
            for pattern in ignore_patterns:
                args.extend(['--exclude', pattern])
            args.extend(['--exclude', '.*'])

            result = subprocess.run(args, capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                files = []
                for line in result.stdout.strip().split('\n'):
                    if line:
                        files.append(line)
                return files
        except (subprocess.TimeoutExpired, FileNotFoundError, subprocess.SubprocessError):
            pass
        return None

    def _get_file_completions(self, at_match):
        prefix = at_match['prefix']
        start_position = at_match['start_position']

        if not self._file_cache:
            return

        # Filter files based on prefix
        matching_files = []
        for file_path in self._file_cache:
            if prefix in file_path:
                matching_files.append(file_path)

        # Sort: directories first, then files
        matching_files.sort(key=lambda x: (not x.endswith('/'), x))

        for file_path in matching_files:
            yield Completion(
                file_path,
                start_position=start_position,
                display=file_path,
            )
