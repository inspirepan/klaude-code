from .diff_utils import generate_diff_lines, generate_snippet_from_diff
from .directory_constants import DEFAULT_IGNORE_PATTERNS, DEFAULT_MAX_CHARS, INDENT_SIZE
from .directory_tree_builder import DirectoryTreeBuilder
from .directory_utils import get_directory_structure, get_effective_ignore_patterns, parse_gitignore
from .file_backup import cleanup_all_backups, cleanup_backup, create_backup, restore_backup
from .file_glob import FileGlob
from .file_readers import read_file_content, read_file_lines_partial
from .file_tracker import CheckModifiedResult, EditHistoryEntry, FileStatus, FileTracker
from .file_validation import (
    EDIT_OLD_STRING_NEW_STRING_IDENTICAL_ERROR_MSG,
    FILE_MODIFIED_ERROR_MSG,
    FILE_NOT_A_FILE_ERROR_MSG,
    FILE_NOT_EXIST_ERROR_MSG,
    FILE_NOT_READ_ERROR_MSG,
    ensure_directory_exists,
    is_image_path,
    validate_file_exists,
)
from .file_writers import write_file_content
from .gitignore_parser import GitIgnoreParser
from .path_utils import get_relative_path_for_display
from .string_operations import count_occurrences, replace_string_in_content, try_colorblind_compatible_match

# Re-export all functionality for backward compatibility
__all__ = [
    # Constants
    'DEFAULT_MAX_CHARS',
    'INDENT_SIZE',
    'DEFAULT_IGNORE_PATTERNS',
    'FILE_NOT_READ_ERROR_MSG',
    'FILE_MODIFIED_ERROR_MSG',
    'FILE_NOT_EXIST_ERROR_MSG',
    'FILE_NOT_A_FILE_ERROR_MSG',
    'EDIT_OLD_STRING_NEW_STRING_IDENTICAL_ERROR_MSG',
    # Classes
    'FileStatus',
    'CheckModifiedResult',
    'EditHistoryEntry',
    'FileTracker',
    'DirectoryTreeBuilder',
    'GitIgnoreParser',
    'FileGlob',
    # Functions - File operations
    'get_relative_path_for_display',
    'read_file_content',
    'read_file_lines_partial',
    'write_file_content',
    'count_occurrences',
    'replace_string_in_content',
    'create_backup',
    'restore_backup',
    'try_colorblind_compatible_match',
    'cleanup_backup',
    'cleanup_all_backups',
    # Functions - Validation
    'validate_file_exists',
    'ensure_directory_exists',
    'is_image_path',
    # Functions - Diff operations
    'generate_diff_lines',
    'generate_snippet_from_diff',
    # Functions - Directory operations
    'parse_gitignore',
    'get_effective_ignore_patterns',
    'get_directory_structure',
]
