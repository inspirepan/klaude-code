import time
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

from .file_validation import FILE_MODIFIED_ERROR_MSG, FILE_NOT_READ_ERROR_MSG


class FileStatus(BaseModel):
    mtime: float
    size: int


class EditHistoryEntry(BaseModel):
    """Records a single edit operation for undo functionality."""

    timestamp: float
    file_path: str
    backup_path: str
    tool_name: str
    operation_summary: str


class CheckModifiedResult(Enum):
    MODIFIED = 'modified'
    NOT_TRACKED = 'not_tracked'
    OS_ACCESS_ERROR = 'os_access_error'
    NOT_MODIFIED = 'not_modified'


class FileTracker(BaseModel):
    """Tracks file modifications and read status using metadata."""

    tracking: Dict[str, FileStatus] = Field(default_factory=dict)
    edit_history: List[EditHistoryEntry] = Field(default_factory=list)

    def track(self, file_path: str) -> None:
        """Track file metadata including mtime and size.

        Args:
            file_path: Path to the file to track
        """
        try:
            stat = Path(file_path).stat()
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
            stat = Path(file_path).stat()
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

    def record_edit(self, file_path: str, backup_path: str, tool_name: str, operation_summary: str) -> None:
        """Record an edit operation for undo functionality.

        Args:
            file_path: Path to the file that was edited
            backup_path: Path to the backup file created before editing
            tool_name: Name of the tool that performed the edit
            operation_summary: Brief description of the edit operation
        """
        entry = EditHistoryEntry(timestamp=time.time(), file_path=file_path, backup_path=backup_path, tool_name=tool_name, operation_summary=operation_summary)
        self.edit_history.append(entry)

        # Keep only the last 10 edits per file to avoid unlimited growth
        file_edits = [e for e in self.edit_history if e.file_path == file_path]
        if len(file_edits) > 10:
            # Remove oldest backup file and entry
            oldest_edit = min(file_edits, key=lambda e: e.timestamp)
            try:
                if Path(oldest_edit.backup_path).exists():
                    Path(oldest_edit.backup_path).unlink()
            except OSError:
                pass
            self.edit_history.remove(oldest_edit)

    def get_last_edit(self, file_path: str) -> Optional[EditHistoryEntry]:
        """Get the most recent edit for a specific file.

        Args:
            file_path: Path to the file to check

        Returns:
            The most recent EditHistoryEntry for the file, or None if no edits found
        """
        file_edits = [e for e in self.edit_history if e.file_path == file_path]
        if not file_edits:
            return None
        return max(file_edits, key=lambda e: e.timestamp)
