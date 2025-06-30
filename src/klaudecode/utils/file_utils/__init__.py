from .diff_utils import generate_char_level_diff, generate_diff_lines, generate_snippet_from_diff, render_diff_lines
from .directory_utils import DEFAULT_IGNORE_PATTERNS, DEFAULT_MAX_CHARS, INDENT_SIZE, TreeNode, get_directory_structure, get_effective_ignore_patterns, parse_gitignore
from .file_operations import (
    cleanup_backup,
    count_occurrences,
    create_backup,
    get_relative_path_for_display,
    read_file_content,
    read_file_lines_partial,
    replace_string_in_content,
    restore_backup,
    write_file_content,
)
from .file_searcher import FileSearcher
from .file_tracker import CheckModifiedResult, FileStatus, FileTracker
from .file_validation import (
    EDIT_OLD_STRING_NEW_STRING_IDENTICAL_ERROR_MSG,
    FILE_MODIFIED_ERROR_MSG,
    FILE_NOT_A_FILE_ERROR_MSG,
    FILE_NOT_EXIST_ERROR_MSG,
    FILE_NOT_READ_ERROR_MSG,
    ensure_directory_exists,
    validate_file_exists,
)

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
    'FileTracker',
    'TreeNode',
    'FileSearcher',
    # Functions - File operations
    'get_relative_path_for_display',
    'read_file_content',
    'read_file_lines_partial',
    'write_file_content',
    'count_occurrences',
    'replace_string_in_content',
    'create_backup',
    'restore_backup',
    'cleanup_backup',
    # Functions - Validation
    'validate_file_exists',
    'ensure_directory_exists',
    # Functions - Diff operations
    'generate_diff_lines',
    'generate_snippet_from_diff',
    'generate_char_level_diff',
    'render_diff_lines',
    # Functions - Directory operations
    'parse_gitignore',
    'get_effective_ignore_patterns',
    'get_directory_structure',
]
