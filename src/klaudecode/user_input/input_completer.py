import asyncio
import os
import shutil
import subprocess
import time
from typing import Callable, Dict, List, Optional

from prompt_toolkit.completion import Completer, Completion

from ..utils.file_utils.directory_utils import DirectoryTreeBuilder, get_effective_ignore_patterns
from .input_command import _SLASH_COMMANDS, Command

DEFAULT_MAX_DEPTH = 5
MAX_FILES_THRESHOLD = 5000
QUICK_SCAN_DEPTH = 2
CACHE_TIMEOUT = 30


class UserInputCompleter(Completer):
    """Custom user input completer"""

    def __init__(self, enable_file_completion_callabck: Callable[[], bool], enable_command_callabck: Callable[[], bool]):
        self.commands: Dict[str, Command] = _SLASH_COMMANDS
        self.enable_file_completion_callabck = enable_file_completion_callabck
        self.enable_command_callabck = enable_command_callabck
        self._file_cache: Optional[List[str]] = None
        self._cache_timestamp: Optional[float] = None
        self._is_caching: bool = False
        asyncio.create_task(self._initialize_file_cache())

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
            if command_part in self.commands:
                command = self.commands[command_part]
                yield Completion('')

    def _find_at_file_pattern(self, text, cursor_position):
        for i in range(cursor_position - 1, -1, -1):
            if text[i] == '@':
                file_prefix = text[i + 1 : cursor_position]
                return {'at_position': i, 'prefix': file_prefix, 'start_position': i + 1 - cursor_position}
            elif text[i].isspace():
                break
        return None

    async def _initialize_file_cache(self):
        """Initialize file cache using smart caching strategy"""
        if self._is_caching:
            return

        self._is_caching = True
        try:
            should_cache = await self._should_enable_caching()
            if not should_cache:
                self._file_cache = []
                return

            max_depth = self._determine_optimal_depth()
            self._file_cache = self._get_files(max_depth=max_depth)
            if self._file_cache:
                self._file_cache.sort()
            self._cache_timestamp = time.time()
        except Exception:
            self._file_cache = []
        finally:
            self._is_caching = False

    async def _should_enable_caching(self) -> bool:
        """Quick check if we should enable file caching based on directory size"""
        try:
            quick_files = self._get_files(max_depth=QUICK_SCAN_DEPTH)
            if len(quick_files) > MAX_FILES_THRESHOLD:
                return False

            total_files = len(os.listdir('.'))
            if total_files > 1000:
                return False

            return True
        except Exception:
            return False

    def _determine_optimal_depth(self) -> int:
        """Determine optimal search depth based on directory structure"""
        try:
            quick_scan = self._get_files(max_depth=QUICK_SCAN_DEPTH)
            files_per_level = len(quick_scan) / QUICK_SCAN_DEPTH if QUICK_SCAN_DEPTH > 0 else 0

            if files_per_level > 500:
                return 3
            elif files_per_level > 200:
                return 4
            else:
                return DEFAULT_MAX_DEPTH
        except Exception:
            return DEFAULT_MAX_DEPTH

    def _get_files(self, max_depth: int = DEFAULT_MAX_DEPTH) -> List[str]:
        """Get file list using fd or find command"""
        files = self._try_fd_command(max_depth=max_depth)
        if files is not None:
            return files
        files = self._get_directory_structure_lines(max_depth=max_depth)
        return files

    def _try_fd_command(self, max_depth: int) -> Optional[List[str]]:
        """Try using fd command"""
        try:
            if not shutil.which('fd'):
                return None
            args = ['fd', '.']
            args.extend(['--maxdepth', str(max_depth)])
            # Add ignore patterns
            for pattern in get_effective_ignore_patterns():
                args.extend(['--exclude', pattern])
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

    def _get_directory_structure_lines(
        self,
        max_depth: int,
    ) -> List[str]:
        builder = DirectoryTreeBuilder(max_depth=max_depth)
        return builder.get_file_list('.')

    def _get_file_completions(self, at_match):
        prefix = at_match['prefix']
        start_position = at_match['start_position']

        if not self._file_cache:
            return

        scored_files = []
        for file_path in self._file_cache:
            if file_path == '.' or prefix not in file_path:
                continue

            filename = file_path.split('/')[-1]
            score = self._calculate_match_score(filename, file_path, prefix)
            if score > 0:
                scored_files.append((score, file_path))

        scored_files.sort(key=lambda x: (-x[0], x[1]))

        for _, file_path in scored_files:
            yield Completion(
                file_path + ' ',
                start_position=start_position,
                display=file_path,
            )

    def _calculate_match_score(self, filename, file_path, prefix):
        """Calculate match score for file completion ranking"""
        if not prefix:
            return 1

        # Exact filename match (highest priority)
        if filename == prefix:
            return 1000

        # Filename starts with prefix (high priority)
        if filename.startswith(prefix):
            return 800

        # Filename contains prefix (medium priority)
        if prefix in filename:
            return 600

        # Path contains prefix (lower priority)
        if prefix in file_path:
            return 400

        return 0
