import os
import shutil
from pathlib import Path


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
