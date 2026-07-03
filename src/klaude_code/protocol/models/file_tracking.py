from __future__ import annotations

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


def build_file_changes_since(before: FileChangeSummary, after: FileChangeSummary) -> list[TaskFileChange]:
    """Return file changes accumulated between two summary snapshots."""

    created_before = set(before.created_files)
    edited_before = set(before.edited_files)
    deleted_before = set(before.deleted_files)
    created_after = set(after.created_files)
    edited_after = set(after.edited_files)
    deleted_after = set(after.deleted_files)
    paths = (
        set(after.file_diffs)
        | (created_after - created_before)
        | (edited_after - edited_before)
        | (deleted_after - deleted_before)
    )

    changes: list[TaskFileChange] = []
    for path in sorted(paths):
        before_stats = before.file_diffs.get(path)
        after_stats = after.file_diffs.get(path)
        added = max((after_stats.added if after_stats else 0) - (before_stats.added if before_stats else 0), 0)
        removed = max((after_stats.removed if after_stats else 0) - (before_stats.removed if before_stats else 0), 0)
        created = path in created_after and path not in created_before
        edited = path in edited_after and path not in edited_before
        deleted = path in deleted_after and path not in deleted_before
        if added == 0 and removed == 0 and not created and not edited and not deleted:
            continue
        changes.append(
            TaskFileChange(path=path, added=added, removed=removed, created=created, edited=edited, deleted=deleted)
        )
    return changes


def merge_file_changes(summary: FileChangeSummary, changes: list[TaskFileChange]) -> None:
    """Apply task-scoped file changes to an accumulated summary."""

    for change in changes:
        if change.created:
            summary.record_created(change.path)
        if change.edited:
            summary.record_edited(change.path)
        if change.deleted:
            summary.record_deleted(change.path)
        if change.added or change.removed:
            summary.add_diff(added=change.added, removed=change.removed, path=change.path)


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


__all__ = [
    "FileChangeSummary",
    "FileDiffStats",
    "FileStatus",
    "TaskFileChange",
    "build_file_changes_since",
    "merge_file_changes",
]
