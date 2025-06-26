import difflib
import hashlib
import os
import re
import shutil
from typing import Dict, List, Tuple

from rich.console import Group
from rich.markup import escape

from ..tui import ColorStyle

"""
- File validation functions (existence, cache status)
- Content processing functions (string replacement, occurrence counting)
- Backup management (creation, restoration, cleanup)
- Diff generation and context snippet display
- Formatting tools (line numbers, content truncation)
- File system operations (directory creation, text file identification)
"""


class FileCache:
    def __init__(self):
        self._cache: Dict[str, Tuple[float, int, str]] = {}

    def _calculate_file_hash_streaming(self, file_path: str, chunk_size: int = 8192) -> str:
        hash_obj = hashlib.md5()
        try:
            with open(file_path, 'rb') as f:
                while chunk := f.read(chunk_size):
                    hash_obj.update(chunk)
            return hash_obj.hexdigest()
        except Exception:
            return ''

    def cache_file_metadata(self, file_path: str):
        try:
            stat = os.stat(file_path)
            mtime = stat.st_mtime
            size = stat.st_size
            content_hash = self._calculate_file_hash_streaming(file_path)
            if content_hash:
                self._cache[file_path] = (mtime, size, content_hash)
        except OSError:
            pass

    def is_file_modified(self, file_path: str) -> Tuple[bool, str]:
        if file_path not in self._cache:
            return True, 'File not in cache'

        try:
            stat = os.stat(file_path)
            cached_mtime, cached_size, cached_hash = self._cache[file_path]

            if stat.st_mtime != cached_mtime or stat.st_size != cached_size:
                return True, 'File modified (mtime or size changed)'

            return False, ''
        except OSError:
            return True, 'File access error'

    def invalidate(self, file_path: str):
        self._cache.pop(file_path, None)

    def clear(self):
        self._cache.clear()

    def get_modified_files(self) -> List[str]:
        modified_files = []
        for file_path in self._cache.keys():
            is_modified, _ = self.is_file_modified(file_path)
            if is_modified:
                modified_files.append(file_path)
        return modified_files


_file_cache = FileCache()

TRUNCATE_CHAR_LIMIT = 5000
TRUNCATE_LINE_LIMIT = 1000
TRUNCATE_LINE_CHAR_LIMIT = 2000
FILE_NOT_READ_ERROR = 'File has not been read yet. Read it first before writing to it.'
FILE_MODIFIED_ERROR = 'File has been modified externally. Either by user or a linter. Read it first before writing to it.'

FILE_NOT_EXIST_ERROR = 'File does not exist.'
FILE_NOT_A_FILE_ERROR = 'EISDIR: illegal operation on a directory, read.'

EDIT_ERROR_OLD_STRING_NEW_STRING_IDENTICAL = 'No changes to make: old_string and new_string are exactly the same.'


def validate_file_exists(file_path: str) -> Tuple[bool, str]:
    if not os.path.exists(file_path):
        return False, FILE_NOT_EXIST_ERROR
    if not os.path.isfile(file_path):
        return False, FILE_NOT_A_FILE_ERROR
    return True, ''


def validate_file_cache(file_path: str) -> Tuple[bool, str]:
    is_modified, error_msg = _file_cache.is_file_modified(file_path)
    if is_modified:
        if error_msg == 'File not in cache':
            return False, FILE_NOT_READ_ERROR
        else:
            return False, FILE_MODIFIED_ERROR
    return True, ''


def cache_file_content(file_path: str):
    _file_cache.cache_file_metadata(file_path)


def get_modified_files() -> List[str]:
    return _file_cache.get_modified_files()


def count_occurrences(content: str, search_string: str) -> int:
    return content.count(search_string)


def replace_string_in_content(content: str, old_string: str, new_string: str, replace_all: bool = False) -> Tuple[str, int]:
    if replace_all:
        new_content = content.replace(old_string, new_string)
        count = content.count(old_string)
    else:
        new_content = content.replace(old_string, new_string, 1)
        count = 1 if old_string in content else 0

    return new_content, count


def create_backup(file_path: str) -> str:
    backup_path = f'{file_path}.backup'
    try:
        shutil.copy2(file_path, backup_path)
        return backup_path
    except Exception as e:
        raise Exception(f'Failed to create backup: {str(e)}')


def restore_backup(file_path: str, backup_path: str):
    try:
        shutil.move(backup_path, file_path)
    except Exception as e:
        raise Exception(f'Failed to restore backup: {str(e)}')


def cleanup_backup(backup_path: str):
    try:
        if os.path.exists(backup_path):
            os.remove(backup_path)
    except Exception:
        pass


def generate_diff_lines(old_content: str, new_content: str) -> List[str]:
    old_lines = old_content.splitlines(keepends=True)
    new_lines = new_content.splitlines(keepends=True)

    diff_lines = list(
        difflib.unified_diff(
            old_lines,
            new_lines,
            lineterm='',
        )
    )

    return diff_lines


def ensure_directory_exists(file_path: str):
    directory = os.path.dirname(file_path)
    if directory:
        os.makedirs(directory, exist_ok=True)


def read_file_content(file_path: str, encoding: str = 'utf-8') -> Tuple[str, str]:
    try:
        with open(file_path, 'r', encoding=encoding) as f:
            content = f.read()
        return content, ''
    except UnicodeDecodeError:
        try:
            with open(file_path, 'r', encoding='latin-1') as f:
                content = f.read()
            return content, '<system-reminder>warning: File decoded using latin-1 encoding</system-reminder>'
        except Exception as e:
            return '', f'Failed to read file: {str(e)}'
    except Exception as e:
        return '', f'Failed to read file: {str(e)}'


def write_file_content(file_path: str, content: str, encoding: str = 'utf-8') -> str:
    try:
        ensure_directory_exists(file_path)
        with open(file_path, 'w', encoding=encoding) as f:
            f.write(content)
        return ''
    except Exception as e:
        return f'Failed to write file: {str(e)}'


def generate_snippet_from_diff(diff_lines: List[str]) -> str:
    """
    Generate a snippet from diff lines that includes context and new content.
    Only includes context lines (' ') and added lines ('+') in line-number→line-content format.
    """
    if not diff_lines:
        return ''

    new_line_num = 1
    snippet_lines = []

    for line in diff_lines:
        if line.startswith('---') or line.startswith('+++'):
            continue
        elif line.startswith('@@'):
            match = re.search(r'@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@', line)
            if match:
                new_line_num = int(match.group(2))
        elif line.startswith('-'):
            continue
        elif line.startswith('+'):
            added_line = line[1:].rstrip('\n\r')
            snippet_lines.append(f'{new_line_num}→{added_line}')
            new_line_num += 1
        elif line.startswith(' '):
            context_line = line[1:].rstrip('\n\r')
            snippet_lines.append(f'{new_line_num}→{context_line}')
            new_line_num += 1

    return '\n'.join(snippet_lines)


def render_diff_lines(diff_lines: List[str]):
    if not diff_lines:
        return ''

    old_line_num = 1
    new_line_num = 1
    width = 3

    lines = []
    for line in diff_lines:
        if line.startswith('---') or line.startswith('+++'):
            continue
        elif line.startswith('@@'):
            match = re.search(r'@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@', line)
            if match:
                old_line_num = int(match.group(1))
                new_line_num = int(match.group(2))
        elif line.startswith('-'):
            removed_line = line[1:].strip('\n\r')
            lines.append(f'[{ColorStyle.DIFF_REMOVED_LINE.value}]{old_line_num:{width}d}:-  {escape(removed_line)}[/{ColorStyle.DIFF_REMOVED_LINE.value}]')
            old_line_num += 1
        elif line.startswith('+'):
            added_line = line[1:].strip('\n\r')
            lines.append(f'[{ColorStyle.DIFF_ADDED_LINE.value}]{new_line_num:{width}d}:+  {escape(added_line)}[/{ColorStyle.DIFF_ADDED_LINE.value}]')
            new_line_num += 1
        elif line.startswith(' '):
            context_line = line[1:].strip('\n\r')
            lines.append(f'{old_line_num:{width}d}:   {escape(context_line)}')
            old_line_num += 1
            new_line_num += 1
        else:
            lines.append(line)
    return Group(*lines)
