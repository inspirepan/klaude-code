import os
import shutil
from pathlib import Path
from typing import Optional, Tuple

from .file_validation import ensure_directory_exists


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


def create_backup(file_path: str) -> str:
    """Create a backup copy of the file in .klaude/backup directory.

    Args:
        file_path: Path to the file to backup

    Returns:
        Path to the backup file

    Raises:
        Exception: If backup creation fails
    """
    import hashlib
    import time

    # Create .klaude/backup directory if it doesn't exist
    backup_dir = Path.cwd() / '.klaude' / 'backup'
    backup_dir.mkdir(parents=True, exist_ok=True)

    # Create unique backup filename using file hash and timestamp
    timestamp = int(time.time() * 1000000)  # microseconds for uniqueness
    file_hash = hashlib.md5(str(Path(file_path).resolve()).encode()).hexdigest()[:8]
    backup_filename = f'{Path(file_path).name}.{file_hash}.{timestamp}'
    backup_path = backup_dir / backup_filename

    try:
        shutil.copy2(file_path, backup_path)
        return str(backup_path)
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


def cleanup_all_backups() -> None:
    """Remove all backup files in .klaude/backup directory."""
    try:
        backup_dir = Path.cwd() / '.klaude' / 'backup'
        if backup_dir.exists():
            # Remove all files in backup directory
            for backup_file in backup_dir.iterdir():
                if backup_file.is_file():
                    backup_file.unlink()
            # Remove backup directory if empty
            try:
                backup_dir.rmdir()
                # Try to remove .klaude directory if it's now empty
                parent_dir = backup_dir.parent
                if parent_dir.name == '.klaude' and not any(parent_dir.iterdir()):
                    parent_dir.rmdir()
            except OSError:
                # Directory not empty, that's fine
                pass
    except Exception:
        # Silently ignore cleanup errors
        pass


def try_colorblind_compatible_match(content: str, old_string: str) -> Tuple[bool, str]:
    """
    Handle model "colorblindness" issue where full tag names might be
    misinterpreted as shortened versions.

    Common patterns:
    - <result> and </result> misinterpreted as <r> and </r>
    - <output> and </output> misinterpreted as <o> and </o>
    - <name> and </name> misinterpreted as <n> and </n>
    - etc.

    This function attempts to find the intended string by expanding
    shortened tags to their full versions.

    Args:
        content: The file content to search in
        old_string: The original string that was not found

    Returns:
        Tuple of (found, corrected_string) where:
        - found: True if a compatible match was found
        - corrected_string: The corrected string that was actually found in content
    """

    # Define mapping of shortened tags to their full versions
    tag_mappings = {
        '<r>': '<result>',
        '</r>': '</result>',
        '<o>': '<output>',
        '</o>': '</output>',
        '<n>': '<name>',
        '</n>': '</name>',
        '<t>': '<type>',
        '</t>': '</type>',
        '<i>': '<input>',
        '</i>': '</input>',
        '<d>': '<description>',
        '</d>': '</description>',
        '<c>': '<content>',
        '</c>': '</content>',
        '<f>': '<function>',
        '</f>': '</function>',
        '<m>': '<method>',
        '</m>': '</method>',
        '<p>': '<parameter>',
        '</p>': '</parameter>',
        '<v>': '<value>',
        '</v>': '</value>',
        '<s>': '<string>',
        '</s>': '</string>',
    }

    # Check if old_string contains any shortened tags
    has_shortened_tags = any(short_tag in old_string for short_tag in tag_mappings.keys())

    if not has_shortened_tags:
        return False, old_string

    # Try expanding all shortened tags to their full versions
    corrected_string = old_string
    for short_tag, full_tag in tag_mappings.items():
        corrected_string = corrected_string.replace(short_tag, full_tag)

    # Check if the corrected string exists in content
    if corrected_string in content:
        return True, corrected_string

    return False, old_string
