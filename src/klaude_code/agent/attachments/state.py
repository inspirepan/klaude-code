from __future__ import annotations

import hashlib
from pathlib import Path

from klaude_code.protocol.models import FileStatus
from klaude_code.session import Session
from klaude_code.tool import build_todo_context
from klaude_code.tool.core.context import ToolContext
from klaude_code.tool.file._utils import hash_text_sha256


def build_attachment_tool_context(session: Session) -> ToolContext:
    return ToolContext(
        file_tracker=session.file_tracker,
        todo_context=build_todo_context(session),
        session_id=session.id,
        work_dir=session.work_dir,
    )


def compute_file_content_sha256(path: str) -> str | None:
    """Compute SHA-256 for file content using the same decoding behavior as ReadTool."""

    try:
        suffix = Path(path).suffix.lower()
        if suffix in {".png", ".jpg", ".jpeg", ".gif", ".webp"}:
            with open(path, "rb") as f:
                return hashlib.sha256(f.read()).hexdigest()

        hasher = hashlib.sha256()
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                hasher.update(line.encode("utf-8"))
        return hasher.hexdigest()
    except (FileNotFoundError, IsADirectoryError, OSError, PermissionError, UnicodeDecodeError):
        return None


def is_tracked_file_unchanged(session: Session, path: str) -> bool:
    status = session.file_tracker.get(path)
    if status is None or status.content_sha256 is None:
        return False

    try:
        current_mtime = Path(path).stat().st_mtime
    except (OSError, FileNotFoundError):
        return False

    if current_mtime == status.mtime:
        return True

    current_sha256 = compute_file_content_sha256(path)
    return current_sha256 is not None and current_sha256 == status.content_sha256


def mark_directory_accessed(session: Session, path: str) -> None:
    existing = session.file_tracker.get(path)
    try:
        mtime = Path(path).stat().st_mtime
    except (OSError, FileNotFoundError):
        mtime = 0.0
    session.file_tracker[path] = FileStatus(
        mtime=mtime,
        content_sha256=None,
        is_memory=existing.is_memory if existing else False,
        is_skill=existing.is_skill if existing else False,
        is_skill_listing=existing.is_skill_listing if existing else False,
        skill_attachment_source=existing.skill_attachment_source if existing else None,
        is_directory=True,
        read_complete=existing.read_complete if existing else False,
    )


def is_memory_loaded(session: Session, path: str) -> bool:
    """Check if a memory file has already been loaded or read unchanged."""

    paths_to_check = [path]
    try:
        resolved = str(Path(path).resolve())
        if resolved != path:
            paths_to_check.append(resolved)
    except OSError:
        pass

    for checked_path in paths_to_check:
        status = session.file_tracker.get(checked_path)
        if status is None:
            continue
        if status.is_memory:
            return True
        if is_tracked_file_unchanged(session, checked_path):
            return True
    return False


def mark_memory_loaded(session: Session, path: str) -> None:
    """Mark a file as loaded memory in file_tracker."""

    try:
        mtime = Path(path).stat().st_mtime
    except (OSError, FileNotFoundError):
        mtime = 0.0
    try:
        content_sha256 = hash_text_sha256(Path(path).read_text(encoding="utf-8", errors="replace"))
    except (OSError, FileNotFoundError, PermissionError, UnicodeDecodeError):
        content_sha256 = None

    paths_to_mark = [path]
    try:
        resolved = str(Path(path).resolve())
        if resolved != path:
            paths_to_mark.append(resolved)
    except OSError:
        pass

    for marked_path in paths_to_mark:
        existing = session.file_tracker.get(marked_path)
        session.file_tracker[marked_path] = FileStatus(
            mtime=mtime,
            content_sha256=content_sha256,
            is_memory=True,
            is_skill=existing.is_skill if existing else False,
            is_skill_listing=existing.is_skill_listing if existing else False,
            skill_attachment_source=existing.skill_attachment_source if existing else None,
            is_directory=existing.is_directory if existing else False,
            read_complete=existing.read_complete if existing else False,
        )
