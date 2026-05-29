"""Shared primitives for ReadTool and its per-format handlers.

Holds the segment-reading dataclasses, line numbering, file-access tracking and
small helpers used by both the tool dispatch (read_tool.py) and the format
handlers (read_handlers.py). Kept separate to avoid a circular import.
"""

from __future__ import annotations

import contextlib
import hashlib
from dataclasses import dataclass
from pathlib import Path

from klaude_code.const import (
    READ_CHAR_LIMIT_PER_LINE,
    READ_GLOBAL_LINE_CAP,
    READ_MAX_CHARS,
    ProjectPaths,
    project_key_from_path,
)
from klaude_code.protocol.models import FileStatus
from klaude_code.tool.core.context import FileTracker, ToolContext
from klaude_code.tool.file._utils import detect_encoding, file_exists, is_directory

_IMAGE_MIME_TYPES: dict[str, str] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}


def _format_numbered_line(line_no: int, content: str) -> str:
    # 6-width right-aligned line number followed by a right arrow
    return f"{line_no:>6}→{content}"


@dataclass
class ReadOptions:
    file_path: str
    offset: int
    limit: int | None
    char_limit_per_line: int | None = READ_CHAR_LIMIT_PER_LINE
    global_line_cap: int | None = READ_GLOBAL_LINE_CAP
    max_total_chars: int | None = READ_MAX_CHARS


@dataclass
class ReadSegmentResult:
    total_lines: int
    selected_lines: list[tuple[int, str]]
    selected_chars_count: int
    remaining_selected_beyond_cap: int
    remaining_due_to_char_limit: int
    content_sha256: str


def _read_segment(options: ReadOptions) -> ReadSegmentResult:
    total_lines = 0
    selected_lines_count = 0
    remaining_selected_beyond_cap = 0
    remaining_due_to_char_limit = 0
    selected_lines: list[tuple[int, str]] = []
    selected_chars = 0
    char_limit_reached = False
    hasher = hashlib.sha256()

    encoding = detect_encoding(options.file_path)
    with open(options.file_path, encoding=encoding, errors="replace") as f:
        for line_no, raw_line in enumerate(f, start=1):
            total_lines = line_no
            hasher.update(raw_line.encode("utf-8"))
            within = line_no >= options.offset and (options.limit is None or selected_lines_count < options.limit)
            if not within:
                continue

            if char_limit_reached:
                remaining_due_to_char_limit += 1
                continue

            selected_lines_count += 1
            content = raw_line.rstrip("\n")
            original_len = len(content)
            if options.char_limit_per_line is not None and original_len > options.char_limit_per_line:
                truncated_chars = original_len - options.char_limit_per_line
                content = (
                    content[: options.char_limit_per_line]
                    + f" … (more {truncated_chars} characters in this line are truncated)"
                )
            line_chars = len(content) + 1
            selected_chars += line_chars

            if options.max_total_chars is not None and selected_chars > options.max_total_chars:
                char_limit_reached = True
                selected_lines.append((line_no, content))
                continue

            if options.global_line_cap is None or len(selected_lines) < options.global_line_cap:
                selected_lines.append((line_no, content))
            else:
                remaining_selected_beyond_cap += 1

    return ReadSegmentResult(
        total_lines=total_lines,
        selected_lines=selected_lines,
        selected_chars_count=selected_chars,
        remaining_selected_beyond_cap=remaining_selected_beyond_cap,
        remaining_due_to_char_limit=remaining_due_to_char_limit,
        content_sha256=hasher.hexdigest(),
    )


def _track_file_access(
    file_tracker: FileTracker | None,
    file_path: str,
    *,
    content_sha256: str | None = None,
    cached_content: str | None = None,
    is_memory: bool = False,
    is_skill: bool = False,
    read_complete: bool = False,
) -> None:
    if file_tracker is None or not file_exists(file_path) or is_directory(file_path):
        return
    with contextlib.suppress(Exception):
        existing = file_tracker.get(file_path)
        is_mem = is_memory or (existing.is_memory if existing else False)
        is_skill_file = is_skill or (existing.is_skill if existing else False)
        is_dir = existing.is_directory if existing else False
        file_tracker[file_path] = FileStatus(
            mtime=Path(file_path).stat().st_mtime,
            content_sha256=content_sha256,
            cached_content=cached_content,
            is_memory=is_mem,
            is_skill=is_skill_file,
            skill_attachment_source=None,
            is_directory=is_dir,
            read_complete=read_complete,
        )


def _is_supported_image_file(file_path: str) -> bool:
    return Path(file_path).suffix.lower() in _IMAGE_MIME_TYPES


def _image_mime_type(file_path: str) -> str:
    suffix = Path(file_path).suffix.lower()
    mime_type = _IMAGE_MIME_TYPES.get(suffix)
    if mime_type is None:
        raise ValueError(f"Unsupported image file extension: {suffix}")
    return mime_type


def _session_images_dir(context: ToolContext) -> Path:
    images_dir = ProjectPaths(project_key=project_key_from_path(context.work_dir)).images_dir(context.session_id)
    images_dir.mkdir(parents=True, exist_ok=True)
    return images_dir


def _truncate_content(content: str, max_chars: int | None) -> tuple[str, bool]:
    """Truncate content to max_chars, returning (content, was_truncated)."""
    if max_chars is None or len(content) <= max_chars:
        return content, False
    return content[:max_chars], True
