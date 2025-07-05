from pathlib import Path
from typing import Tuple

# Error messages
FILE_NOT_READ_ERROR_MSG = 'File has not been read yet. Read it first before writing to it.'
FILE_MODIFIED_ERROR_MSG = 'File has been modified externally. Either by user or a linter. Read it first before writing to it.'
FILE_NOT_EXIST_ERROR_MSG = 'File does not exist.'
FILE_NOT_A_FILE_ERROR_MSG = 'EISDIR: illegal operation on a directory.'
EDIT_OLD_STRING_NEW_STRING_IDENTICAL_ERROR_MSG = 'No changes to make: old_string and new_string are exactly the same.'


IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp', '.svg'}


def is_image_path(text: str) -> bool:
    """Check if text is a valid image file path."""
    try:
        path = Path(text.strip())
        # Check if it's a valid path and has image extension
        if path.suffix.lower() in IMAGE_EXTENSIONS:
            # Check if file exists
            if path.exists() and path.is_file():
                return True
    except Exception:
        pass
    return False


def validate_file_exists(file_path: str) -> Tuple[bool, str]:
    """Validate that file exists and is a regular file.

    Args:
        file_path: Path to validate

    Returns:
        Tuple of (is_valid, error_message)
    """
    if not Path(file_path).exists():
        return False, FILE_NOT_EXIST_ERROR_MSG
    if not Path(file_path).is_file():
        return False, FILE_NOT_A_FILE_ERROR_MSG
    return True, ''


def ensure_directory_exists(file_path: str) -> None:
    """Ensure parent directory of file path exists.

    Args:
        file_path: File path whose parent directory should exist
    """
    directory = Path(file_path).parent
    if directory:
        directory.mkdir(parents=True, exist_ok=True)
