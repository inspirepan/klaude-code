import difflib
import fnmatch
import os
import re
import shutil
from collections import deque
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from pydantic import BaseModel, Field
from rich.console import Group
from rich.table import Table
from rich.text import Text

from ..tui import ColorStyle

# Directory structure constants
DEFAULT_MAX_CHARS = 40000
INDENT_SIZE = 2

# Error messages
FILE_NOT_READ_ERROR_MSG = 'File has not been read yet. Read it first before writing to it.'
FILE_MODIFIED_ERROR_MSG = 'File has been modified externally. Either by user or a linter. Read it first before writing to it.'
FILE_NOT_EXIST_ERROR_MSG = 'File does not exist.'
FILE_NOT_A_FILE_ERROR_MSG = 'EISDIR: illegal operation on a directory.'
EDIT_OLD_STRING_NEW_STRING_IDENTICAL_ERROR_MSG = 'No changes to make: old_string and new_string are exactly the same.'


DEFAULT_IGNORE_PATTERNS = [
    'node_modules',
    '.git',
    '.svn',
    '.hg',
    '.bzr',
    '__pycache__',
    '.pytest_cache',
    '.mypy_cache',
    '.tox',
    '.venv',
    'venv',
    '.env',
    '.virtualenv',
    'dist',
    'build',
    'target',
    'out',
    'bin',
    'obj',
    '.DS_Store',
    'Thumbs.db',
    '*.tmp',
    '*.temp',
    '*.log',
    '*.cache',
    '*.lock',
    '*.jpg',
    '*.jpeg',
    '*.png',
    '*.gif',
    '*.bmp',
    '*.svg',
    '*.mp4',
    '*.mov',
    '*.avi',
    '*.mkv',
    '*.webm',
    '*.mp3',
    '*.wav',
    '*.flac',
    '*.ogg',
    '*.zip',
    '*.tar',
    '*.gz',
    '*.bz2',
    '*.xz',
    '*.7z',
    '*.pdf',
    '*.doc',
    '*.docx',
    '*.xls',
    '*.xlsx',
    '*.ppt',
    '*.pptx',
    '*.exe',
    '*.dll',
    '*.so',
    '*.dylib',
]


def parse_gitignore(gitignore_path: str) -> List[str]:
    """Parse .gitignore file and return list of ignore patterns.

    Args:
        gitignore_path: Path to .gitignore file

    Returns:
        List of ignore patterns
    """
    patterns = []

    if not os.path.exists(gitignore_path):
        return patterns

    try:
        with open(gitignore_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    if line.startswith('!'):
                        continue
                    patterns.append(line)
    except Exception:
        pass

    return patterns


def get_effective_ignore_patterns(additional_patterns: Optional[List[str]] = None) -> List[str]:
    """Get effective ignore patterns by combining defaults with .gitignore.

    Args:
        additional_patterns: Additional patterns to include

    Returns:
        Combined list of ignore patterns
    """
    patterns = DEFAULT_IGNORE_PATTERNS.copy()

    gitignore_path = os.path.join(os.getcwd(), '.gitignore')
    gitignore_patterns = parse_gitignore(gitignore_path)
    patterns.extend(gitignore_patterns)

    if additional_patterns:
        patterns.extend(additional_patterns)

    return patterns


def get_relative_path_for_display(file_path: str) -> str:
    """Convert absolute path to relative path for display purposes.

    Args:
        file_path: Absolute file path to convert

    Returns:
        Relative path if shorter than absolute path, otherwise absolute path
    """
    try:
        abs_path = Path(file_path).resolve()
        relative_path = abs_path.relative_to(Path.cwd())
        relative_str = str(relative_path)
        return relative_str if len(relative_str) < len(file_path) else file_path
    except (ValueError, OSError):
        return file_path


class FileStatus(BaseModel):
    mtime: float
    size: int


class CheckModifiedResult(Enum):
    MODIFIED = 'modified'
    NOT_TRACKED = 'not_tracked'
    OS_ACCESS_ERROR = 'os_access_error'
    NOT_MODIFIED = 'not_modified'


class FileTracker(BaseModel):
    """Tracks file modifications and read status using metadata."""

    tracking: Dict[str, FileStatus] = Field(default_factory=dict)

    def track(self, file_path: str) -> None:
        """Track file metadata including mtime and size.

        Args:
            file_path: Path to the file to track
        """
        try:
            stat = os.stat(file_path)
            self.tracking[file_path] = FileStatus(mtime=stat.st_mtime, size=stat.st_size)
        except OSError:
            pass

    def check_modified(self, file_path: str) -> CheckModifiedResult:
        """Check if file has been modified since last tracking.

        Args:
            file_path: Path to the file to check

        Returns:
            Tuple of (is_modified, reason)
        """
        if file_path not in self.tracking:
            return CheckModifiedResult.NOT_TRACKED

        try:
            stat = os.stat(file_path)
            tracked_status = self.tracking[file_path]

            if stat.st_mtime != tracked_status.mtime or stat.st_size != tracked_status.size:
                return CheckModifiedResult.MODIFIED

            return CheckModifiedResult.NOT_MODIFIED
        except OSError:
            return CheckModifiedResult.OS_ACCESS_ERROR

    def remove(self, file_path: str):
        """Remove file from tracking.

        Args:
            file_path: Path to remove from tracking
        """
        if file_path in self.tracking:
            self.tracking.pop(file_path)

    def clear(self) -> None:
        """Clear all tracked file metadata."""
        self.tracking.clear()

    def get_all_modified(self) -> List[str]:
        """Get list of all files that have been modified or deleted since tracking.

        Returns:
            List of file paths that have been modified or deleted
        """
        modified_files = []
        for file_path in self.tracking.keys():
            check_modified_result = self.check_modified(file_path)
            if check_modified_result == CheckModifiedResult.MODIFIED or check_modified_result == CheckModifiedResult.OS_ACCESS_ERROR:
                modified_files.append(file_path)
        return modified_files

    def validate_track(self, file_path: str) -> Tuple[bool, str]:
        """Validate that file is properly tracked and not modified.

        Args:
            file_path: Path to validate

        Returns:
            Tuple of (is_valid, error_message)
        """
        check_modified_result = self.check_modified(file_path)
        if check_modified_result == CheckModifiedResult.NOT_TRACKED:
            return False, FILE_NOT_READ_ERROR_MSG
        elif check_modified_result == CheckModifiedResult.MODIFIED:
            return False, FILE_MODIFIED_ERROR_MSG
        elif check_modified_result == CheckModifiedResult.OS_ACCESS_ERROR:
            return False, FILE_MODIFIED_ERROR_MSG
        return True, ''


def validate_file_exists(file_path: str) -> Tuple[bool, str]:
    """Validate that file exists and is a regular file.

    Args:
        file_path: Path to validate

    Returns:
        Tuple of (is_valid, error_message)
    """
    if not os.path.exists(file_path):
        return False, FILE_NOT_EXIST_ERROR_MSG
    if not os.path.isfile(file_path):
        return False, FILE_NOT_A_FILE_ERROR_MSG
    return True, ''


def ensure_directory_exists(file_path: str) -> None:
    """Ensure parent directory of file path exists.

    Args:
        file_path: File path whose parent directory should exist
    """
    directory = os.path.dirname(file_path)
    if directory:
        os.makedirs(directory, exist_ok=True)


# String operations
def count_occurrences(content: str, search_string: str) -> int:
    """Count occurrences of search string in content.

    Args:
        content: Text content to search
        search_string: String to count

    Returns:
        Number of occurrences
    """
    return content.count(search_string)


def replace_string_in_content(content: str, old_string: str, new_string: str, replace_all: bool = False) -> Tuple[str, int]:
    """Replace occurrences of old_string with new_string in content.

    Args:
        content: Text content to modify
        old_string: String to replace
        new_string: Replacement string
        replace_all: Whether to replace all occurrences or just first

    Returns:
        Tuple of (modified_content, replacement_count)
    """
    if replace_all:
        new_content = content.replace(old_string, new_string)
        count = content.count(old_string)
    else:
        new_content = content.replace(old_string, new_string, 1)
        count = 1 if old_string in content else 0

    return new_content, count


# File backup operations
def create_backup(file_path: str) -> str:
    """Create a backup copy of the file.

    Args:
        file_path: Path to the file to backup

    Returns:
        Path to the backup file

    Raises:
        Exception: If backup creation fails
    """
    backup_path = f'{file_path}.backup'
    try:
        shutil.copy2(file_path, backup_path)
        return backup_path
    except Exception as e:
        raise Exception(f'Failed to create backup: {str(e)}')


def restore_backup(file_path: str, backup_path: str) -> None:
    """Restore file from backup.

    Args:
        file_path: Original file path
        backup_path: Path to backup file

    Raises:
        Exception: If restore fails
    """
    try:
        shutil.move(backup_path, file_path)
    except Exception as e:
        raise Exception(f'Failed to restore backup: {str(e)}')


def cleanup_backup(backup_path: str) -> None:
    """Remove backup file if it exists.

    Args:
        backup_path: Path to backup file to remove
    """
    try:
        if os.path.exists(backup_path):
            os.remove(backup_path)
    except Exception:
        pass


# File I/O operations
def read_file_content(file_path: str, encoding: str = 'utf-8') -> Tuple[str, str]:
    """Read file content with fallback encoding handling.

    Args:
        file_path: Path to file to read
        encoding: Primary encoding to try

    Returns:
        Tuple of (content, warning_message)
    """
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


def read_file_lines_partial(file_path: str, offset: Optional[int] = None, limit: Optional[int] = None) -> tuple[list[str], str]:
    """Read file lines with offset and limit to avoid loading entire file into memory"""
    try:
        lines = []
        with open(file_path, 'r', encoding='utf-8') as f:
            if offset is not None and offset > 1:
                for _ in range(offset - 1):
                    try:
                        next(f)
                    except StopIteration:
                        break

            count = 0
            max_lines = limit if limit is not None else float('inf')

            for line in f:
                if count >= max_lines:
                    break
                lines.append(line.rstrip('\n\r'))
                count += 1

        return lines, ''
    except UnicodeDecodeError:
        try:
            lines = []
            with open(file_path, 'r', encoding='latin-1') as f:
                if offset is not None and offset > 1:
                    for _ in range(offset - 1):
                        try:
                            next(f)
                        except StopIteration:
                            break

                count = 0
                max_lines = limit if limit is not None else float('inf')

                for line in f:
                    if count >= max_lines:
                        break
                    lines.append(line.rstrip('\n\r'))
                    count += 1

            return lines, '<system-reminder>warning: File decoded using latin-1 encoding</system-reminder>'
        except Exception as e:
            return [], f'Failed to read file: {str(e)}'
    except Exception as e:
        return [], f'Failed to read file: {str(e)}'


def write_file_content(file_path: str, content: str, encoding: str = 'utf-8') -> str:
    """Write content to file, creating parent directories if needed.

    Args:
        file_path: Path to write to
        content: Content to write
        encoding: Encoding to use

    Returns:
        Error message if write fails, empty string on success
    """
    try:
        ensure_directory_exists(file_path)
        with open(file_path, 'w', encoding=encoding) as f:
            f.write(content)
        return ''
    except Exception as e:
        return f'Failed to write file: {str(e)}'


# File diff operations
def generate_diff_lines(old_content: str, new_content: str) -> List[str]:
    """Generate unified diff lines between old and new content.

    Args:
        old_content: Original content
        new_content: Modified content

    Returns:
        List of diff lines in unified format
    """
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


def generate_snippet_from_diff(diff_lines: List[str]) -> str:
    """Generate a snippet from diff lines showing context and new content.

    Only includes context lines (' ') and added lines ('+') in line-number→line-content format.

    Args:
        diff_lines: List of unified diff lines

    Returns:
        Formatted snippet string
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


def generate_char_level_diff(old_line: str, new_line: str) -> Tuple[Text, Text]:
    """Generate character-level diff for two lines.

    Args:
        old_line: Original line content
        new_line: Modified line content

    Returns:
        Tuple of (styled_old_line, styled_new_line)
    """
    matcher = difflib.SequenceMatcher(None, old_line, new_line)

    old_text = Text()
    new_text = Text()

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        old_segment = old_line[i1:i2]
        new_segment = new_line[j1:j2]

        if tag == 'equal':
            old_text.append(old_segment, style=ColorStyle.DIFF_REMOVED_LINE.value)
            new_text.append(new_segment, style=ColorStyle.DIFF_ADDED_LINE.value)
        elif tag == 'delete':
            old_text.append(old_segment, style=ColorStyle.DIFF_REMOVED_CHAR.value)
            # No corresponding text in new line
        elif tag == 'insert':
            # No corresponding text in old line
            new_text.append(new_segment, style=ColorStyle.DIFF_ADDED_CHAR.value)
        elif tag == 'replace':
            old_text.append(old_segment, style=ColorStyle.DIFF_REMOVED_CHAR.value)
            new_text.append(new_segment, style=ColorStyle.DIFF_ADDED_CHAR.value)

    return old_text, new_text


def render_diff_lines(diff_lines: List[str]) -> Group:
    """Render diff lines with color formatting for terminal display.

    Args:
        diff_lines: List of unified diff lines

    Returns:
        Rich Group object with formatted diff content
    """
    if not diff_lines:
        return ''

    old_line_num = 1
    new_line_num = 1
    width = 3

    grid = Table.grid(padding=(0, 0))
    grid.add_column()
    grid.add_column()
    grid.add_column(overflow='fold')

    add_line_symbol = Text('+ ')
    add_line_symbol.stylize(ColorStyle.DIFF_ADDED_LINE.value)
    remove_line_symbol = Text('- ')
    remove_line_symbol.stylize(ColorStyle.DIFF_REMOVED_LINE.value)
    context_line_symbol = Text('  ')

    def _is_single_line_change(start_idx: int) -> bool:
        """Check if this is a single line removal followed by single line addition between context lines."""
        if start_idx == 0 or start_idx >= len(diff_lines) - 2:
            return False

        # Check if previous line is context or start of hunk
        prev_line = diff_lines[start_idx - 1]
        if not (prev_line.startswith(' ') or prev_line.startswith('@@')):
            return False

        # Check if current is single '-' and next is single '+'
        current_line = diff_lines[start_idx]
        next_line = diff_lines[start_idx + 1]
        if not (current_line.startswith('-') and next_line.startswith('+')):
            return False

        # Check if the line after '+' is context or end of diff
        if start_idx + 2 < len(diff_lines):
            after_plus = diff_lines[start_idx + 2]
            if not (after_plus.startswith(' ') or after_plus.startswith('@@') or after_plus.startswith('---') or after_plus.startswith('+++')):
                return False

        return True

    # Parse the diff to find consecutive remove/add pairs
    i = 0
    while i < len(diff_lines):
        line = diff_lines[i]

        if line.startswith('---') or line.startswith('+++'):
            i += 1
            continue
        elif line.startswith('@@'):
            match = re.search(r'@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@', line)
            if match:
                old_line_num = int(match.group(1))
                new_line_num = int(match.group(2))
            i += 1
            continue
        elif line.startswith('-'):
            # Check if next line is an add (indicating a modification)
            removed_line = line[1:].strip('\n\r')
            if i + 1 < len(diff_lines) and diff_lines[i + 1].startswith('+'):
                added_line = diff_lines[i + 1][1:].strip('\n\r')

                # Only do character-level diff for single line changes between context lines
                if _is_single_line_change(i):
                    styled_old, styled_new = generate_char_level_diff(removed_line, added_line)
                    grid.add_row(Text(f'{old_line_num:{width}d} '), remove_line_symbol, styled_old)
                    grid.add_row(Text(f'{new_line_num:{width}d} '), add_line_symbol, styled_new)
                else:
                    # Use simple line-level styling for consecutive changes
                    old_text = Text(removed_line)
                    old_text.stylize(ColorStyle.DIFF_REMOVED_LINE.value)
                    new_text = Text(added_line)
                    new_text.stylize(ColorStyle.DIFF_ADDED_LINE.value)
                    grid.add_row(Text(f'{old_line_num:{width}d} '), remove_line_symbol, old_text)
                    grid.add_row(Text(f'{new_line_num:{width}d} '), add_line_symbol, new_text)

                old_line_num += 1
                new_line_num += 1
                i += 2  # Skip both lines
            else:
                # Pure removal
                text = Text(removed_line)
                text.stylize(ColorStyle.DIFF_REMOVED_LINE.value)
                grid.add_row(Text(f'{old_line_num:{width}d} '), remove_line_symbol, text)
                old_line_num += 1
                i += 1
        elif line.startswith('+'):
            # Pure addition (not part of a modification pair)
            added_line = line[1:].strip('\n\r')
            text = Text(added_line)
            text.stylize(ColorStyle.DIFF_ADDED_LINE.value)
            grid.add_row(Text(f'{new_line_num:{width}d} '), add_line_symbol, text)
            new_line_num += 1
            i += 1
        elif line.startswith(' '):
            context_line = line[1:].strip('\n\r')
            text = Text(context_line)
            text.stylize(ColorStyle.CONTEXT_LINE.value)
            grid.add_row(Text(f'{new_line_num:{width}d} '), context_line_symbol, text)
            old_line_num += 1
            new_line_num += 1
            i += 1
        else:
            grid.add_row('', '', Text(line))
            i += 1

    return grid


# Directory operations


class TreeNode:
    """Represents a node in the directory tree."""

    def __init__(self, name: str, path: str, is_dir: bool, depth: int):
        self.name = name
        self.path = path
        self.is_dir = is_dir
        self.depth = depth
        self.children: List['TreeNode'] = []


def _should_ignore_path(item_path: str, item_name: str, ignore_patterns: List[str], show_hidden: bool) -> bool:
    """Check if a path should be ignored based on patterns and settings.

    Args:
        item_path: Full path to the item
        item_name: Name of the item
        ignore_patterns: List of patterns to ignore
        show_hidden: Whether to show hidden files

    Returns:
        True if path should be ignored
    """
    if not show_hidden and item_name.startswith('.') and item_name not in ['.', '..']:
        return True

    for pattern in ignore_patterns:
        if pattern.endswith('/'):
            if fnmatch.fnmatch(item_name + '/', pattern) or fnmatch.fnmatch(item_path + '/', pattern):
                return True
        else:
            if fnmatch.fnmatch(item_name, pattern) or fnmatch.fnmatch(item_path, pattern):
                return True
    return False


def _build_directory_tree(root_path: str, ignore_patterns: List[str], max_chars: int, max_depth: Optional[int], show_hidden: bool) -> Tuple[TreeNode, int, bool]:
    """Build directory tree using breadth-first traversal.

    Args:
        root_path: Root directory path
        ignore_patterns: Patterns to ignore
        max_chars: Maximum character limit
        max_depth: Maximum depth
        show_hidden: Whether to show hidden files

    Returns:
        Tuple of (root_node, path_count, truncated)
    """
    root = TreeNode(os.path.basename(root_path) or root_path, root_path, True, 0)
    queue = deque([root])
    path_count = 0
    char_budget = max_chars if max_chars > 0 else float('inf')
    truncated = False

    while queue and char_budget > 0:
        current_node = queue.popleft()

        if max_depth is not None and current_node.depth >= max_depth:
            continue

        if not current_node.is_dir:
            continue

        try:
            items = os.listdir(current_node.path)
        except (PermissionError, OSError):
            continue

        dirs = []
        files = []

        for item in items:
            item_path = os.path.join(current_node.path, item)

            if _should_ignore_path(item_path, item, ignore_patterns, show_hidden):
                continue

            if os.path.isdir(item_path):
                dirs.append(item)
            else:
                files.append(item)

        dirs.sort()
        files.sort()

        for item in dirs + files:
            item_path = os.path.join(current_node.path, item)
            is_dir = os.path.isdir(item_path)
            child_node = TreeNode(item, item_path, is_dir, current_node.depth + 1)
            current_node.children.append(child_node)
            path_count += 1

            estimated_chars = (child_node.depth * INDENT_SIZE) + len(child_node.name) + 3
            if char_budget - estimated_chars <= 0:
                truncated = True
                break
            char_budget -= estimated_chars

            if is_dir:
                queue.append(child_node)

        if truncated:
            break

    return root, path_count, truncated


def _format_tree_node(node: TreeNode) -> List[str]:
    """Format tree node and its children into display lines.

    Args:
        node: Tree node to format

    Returns:
        List of formatted lines
    """
    lines = []

    def traverse(current_node: TreeNode):
        if current_node.depth == 0:
            display_name = current_node.path + '/' if current_node.is_dir else current_node.path
            lines.append(f'- {display_name}')
        else:
            indent = '  ' * current_node.depth
            display_name = current_node.name + '/' if current_node.is_dir else current_node.name
            lines.append(f'{indent}- {display_name}')

        for child in current_node.children:
            traverse(child)

    traverse(node)
    return lines


def get_directory_structure(
    path: str, ignore_pattern: Optional[List[str]] = None, max_chars: int = DEFAULT_MAX_CHARS, max_depth: Optional[int] = None, show_hidden: bool = False
) -> Tuple[str, bool, int]:
    """Generate a text representation of directory structure.

    Uses breadth-first traversal to build tree structure, then formats output
    in depth-first manner for better readability.

    Args:
        path: Directory path to analyze
        ignore_pattern: Additional ignore patterns list (optional)
        max_chars: Maximum character limit, 0 means unlimited
        max_depth: Maximum depth, None means unlimited
        show_hidden: Whether to show hidden files

    Returns:
        Tuple[str, bool, int]: (content, truncated, path_count)
        - content: Formatted directory tree text
        - truncated: Whether truncated due to character limit
        - path_count: Number of path items included
    """
    if not os.path.exists(path):
        return f'Path does not exist: {path}', False, 0

    if not os.path.isdir(path):
        return f'Path is not a directory: {path}', False, 0

    all_ignore_patterns = get_effective_ignore_patterns(ignore_pattern)

    root_node, path_count, truncated = _build_directory_tree(path, all_ignore_patterns, max_chars, max_depth, show_hidden)

    lines = _format_tree_node(root_node)
    content = '\n'.join(lines)

    if truncated:
        content += f'\n... (truncated at {max_chars} characters, use LS tool with specific paths to explore more)'

    return content, truncated, path_count
