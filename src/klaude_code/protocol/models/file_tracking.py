from typing import Literal

from pydantic import BaseModel, Field


class FileDiffStats(BaseModel):
    added: int = 0
    removed: int = 0


class FileChangeSummary(BaseModel):
    created_files: list[str] = Field(default_factory=list)
    edited_files: list[str] = Field(default_factory=list)
    deleted_files: list[str] = Field(default_factory=list)
    diff_lines_added: int = 0
    diff_lines_removed: int = 0
    file_diffs: dict[str, FileDiffStats] = Field(default_factory=dict)

    def record_created(self, path: str) -> None:
        if path not in self.created_files:
            self.created_files.append(path)

    def record_edited(self, path: str) -> None:
        if path not in self.edited_files:
            self.edited_files.append(path)

    def record_deleted(self, path: str) -> None:
        if path not in self.deleted_files:
            self.deleted_files.append(path)

    def add_diff(self, *, added: int, removed: int, path: str | None = None) -> None:
        self.diff_lines_added += added
        self.diff_lines_removed += removed
        if path is None:
            return
        stats = self.file_diffs.get(path)
        if stats is None:
            stats = FileDiffStats()
            self.file_diffs[path] = stats
        stats.added += added
        stats.removed += removed


class TaskFileChange(BaseModel):
    path: str
    added: int = 0
    removed: int = 0
    created: bool = False
    edited: bool = False
    deleted: bool = False


class FileStatus(BaseModel):
    """Tracks file state including modification time and content hash."""

    mtime: float
    content_sha256: str | None = None
    cached_content: str | None = Field(default=None, exclude=True)
    is_memory: bool = False
    is_skill: bool = False
    is_skill_listing: bool = False
    skill_listing_paths_by_name: dict[str, str] | None = None
    skill_attachment_source: Literal["dynamic", "explicit"] | None = None
    is_directory: bool = False
    read_complete: bool = False


__all__ = ["FileChangeSummary", "FileDiffStats", "FileStatus", "TaskFileChange"]
