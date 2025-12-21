from __future__ import annotations

import asyncio
import contextlib
import hashlib
import os
from base64 import b64encode
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, Field

from klaude_code import const
from klaude_code.core.tool.file._utils import file_exists, is_directory
from klaude_code.core.tool.tool_abc import ToolABC, load_desc
from klaude_code.core.tool.tool_context import get_current_file_tracker
from klaude_code.core.tool.tool_registry import register
from klaude_code.protocol import llm_param, model, tools

_IMAGE_MIME_TYPES: dict[str, str] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}

_BINARY_CHECK_SIZE = 8192


def _is_binary_file(file_path: str) -> bool:
    """Check if a file is binary by looking for null bytes in the first chunk."""
    try:
        with open(file_path, "rb") as f:
            chunk = f.read(_BINARY_CHECK_SIZE)
            return b"\x00" in chunk
    except OSError:
        return False


def _format_numbered_line(line_no: int, content: str) -> str:
    # 6-width right-aligned line number followed by a right arrow
    return f"{line_no:>6}→{content}"


@dataclass
class ReadOptions:
    file_path: str
    offset: int
    limit: int | None
    char_limit_per_line: int | None = const.READ_CHAR_LIMIT_PER_LINE
    global_line_cap: int | None = const.READ_GLOBAL_LINE_CAP
    max_total_chars: int | None = const.READ_MAX_CHARS


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

    with open(options.file_path, encoding="utf-8", errors="replace") as f:
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
                    + f" ... (more {truncated_chars} characters in this line are truncated)"
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


def _track_file_access(file_path: str, *, content_sha256: str | None = None, is_memory: bool = False) -> None:
    file_tracker = get_current_file_tracker()
    if file_tracker is None or not file_exists(file_path) or is_directory(file_path):
        return
    with contextlib.suppress(Exception):
        existing = file_tracker.get(file_path)
        is_mem = is_memory or (existing.is_memory if existing else False)
        file_tracker[file_path] = model.FileStatus(
            mtime=Path(file_path).stat().st_mtime,
            content_sha256=content_sha256,
            is_memory=is_mem,
        )


def _is_supported_image_file(file_path: str) -> bool:
    return Path(file_path).suffix.lower() in _IMAGE_MIME_TYPES


def _image_mime_type(file_path: str) -> str:
    suffix = Path(file_path).suffix.lower()
    mime_type = _IMAGE_MIME_TYPES.get(suffix)
    if mime_type is None:
        raise ValueError(f"Unsupported image file extension: {suffix}")
    return mime_type


@register(tools.READ)
class ReadTool(ToolABC):
    class ReadArguments(BaseModel):
        file_path: str
        offset: int | None = Field(default=None)
        limit: int | None = Field(default=None)

    @classmethod
    def schema(cls) -> llm_param.ToolSchema:
        return llm_param.ToolSchema(
            name=tools.READ,
            type="function",
            description=load_desc(Path(__file__).parent / "read_tool.md"),
            parameters={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "The absolute path to the file to read",
                    },
                    "offset": {
                        "type": "number",
                        "description": "The line number to start reading from. Only provide if the file is too large to read at once",
                    },
                    "limit": {
                        "type": "number",
                        "description": "The number of lines to read. Only provide if the file is too large to read at once.",
                    },
                },
                "required": ["file_path"],
                "additionalProperties": False,
            },
        )

    @classmethod
    async def call(cls, arguments: str) -> model.ToolResultItem:
        try:
            args = ReadTool.ReadArguments.model_validate_json(arguments)
        except Exception as e:  # pragma: no cover - defensive
            return model.ToolResultItem(status="error", output=f"Invalid arguments: {e}")
        return await cls.call_with_args(args)

    @classmethod
    def _effective_limits(cls) -> tuple[int | None, int | None, int | None]:
        return (
            const.READ_CHAR_LIMIT_PER_LINE,
            const.READ_GLOBAL_LINE_CAP,
            const.READ_MAX_CHARS,
        )

    @classmethod
    async def call_with_args(cls, args: ReadTool.ReadArguments) -> model.ToolResultItem:
        file_path = os.path.abspath(args.file_path)
        char_per_line, line_cap, max_chars = cls._effective_limits()

        if is_directory(file_path):
            return model.ToolResultItem(
                status="error",
                output="<tool_use_error>Illegal operation on a directory. read</tool_use_error>",
            )
        if not file_exists(file_path):
            return model.ToolResultItem(
                status="error",
                output="<tool_use_error>File does not exist.</tool_use_error>",
            )

        # Check for PDF files
        if Path(file_path).suffix.lower() == ".pdf":
            return model.ToolResultItem(
                status="error",
                output=(
                    "<tool_use_error>PDF files are not supported by this tool.\n"
                    "If there's an available skill for PDF, use it.\n"
                    "Or use a Python script with `pdfplumber` to extract text/tables:\n\n"
                    "```python\n"
                    "# /// script\n"
                    '# dependencies = ["pdfplumber"]\n'
                    "# ///\n"
                    "import pdfplumber\n\n"
                    "with pdfplumber.open('file.pdf') as pdf:\n"
                    "    for page in pdf.pages:\n"
                    "        print(page.extract_text())\n"
                    "```\n"
                    "</tool_use_error>"
                ),
            )

        is_image_file = _is_supported_image_file(file_path)
        # Check for binary files (skip for images which are handled separately)
        if not is_image_file and _is_binary_file(file_path):
            return model.ToolResultItem(
                status="error",
                output=(
                    "<tool_use_error>This appears to be a binary file and cannot be read as text. "
                    "Use appropriate tools or libraries to handle binary files.</tool_use_error>"
                ),
            )

        try:
            size_bytes = Path(file_path).stat().st_size
        except OSError:
            size_bytes = 0

        if is_image_file:
            if size_bytes > const.READ_MAX_IMAGE_BYTES:
                size_mb = size_bytes / (1024 * 1024)
                return model.ToolResultItem(
                    status="error",
                    output=(
                        f"<tool_use_error>Image size ({size_mb:.2f}MB) exceeds maximum supported size (4.00MB) for inline transfer.</tool_use_error>"
                    ),
                )
            try:
                mime_type = _image_mime_type(file_path)
                with open(file_path, "rb") as image_file:
                    image_bytes = image_file.read()
                data_url = f"data:{mime_type};base64,{b64encode(image_bytes).decode('ascii')}"
            except Exception as exc:
                return model.ToolResultItem(
                    status="error",
                    output=f"<tool_use_error>Failed to read image file: {exc}</tool_use_error>",
                )

            _track_file_access(file_path, content_sha256=hashlib.sha256(image_bytes).hexdigest())
            size_kb = size_bytes / 1024.0 if size_bytes else 0.0
            output_text = f"[image] {Path(file_path).name} ({size_kb:.1f}KB)"
            image_part = model.ImageURLPart(image_url=model.ImageURLPart.ImageURL(url=data_url, id=None))
            return model.ToolResultItem(status="success", output=output_text, images=[image_part])

        offset = 1 if args.offset is None or args.offset < 1 else int(args.offset)
        limit = None if args.limit is None else int(args.limit)
        if limit is not None and limit < 0:
            limit = 0

        try:
            read_result = await asyncio.to_thread(
                _read_segment,
                ReadOptions(
                    file_path=file_path,
                    offset=offset,
                    limit=limit,
                    char_limit_per_line=char_per_line,
                    global_line_cap=line_cap,
                    max_total_chars=max_chars,
                ),
            )

        except FileNotFoundError:
            return model.ToolResultItem(
                status="error",
                output="<tool_use_error>File does not exist.</tool_use_error>",
            )
        except IsADirectoryError:
            return model.ToolResultItem(
                status="error",
                output="<tool_use_error>Illegal operation on a directory. read</tool_use_error>",
            )

        if offset > max(read_result.total_lines, 0):
            warn = f"<system-reminder>Warning: the file exists but is shorter than the provided offset ({offset}). The file has {read_result.total_lines} lines.</system-reminder>"
            _track_file_access(file_path, content_sha256=read_result.content_sha256)
            return model.ToolResultItem(status="success", output=warn)

        lines_out: list[str] = [_format_numbered_line(no, content) for no, content in read_result.selected_lines]

        # Show truncation info with reason
        if read_result.remaining_due_to_char_limit > 0:
            lines_out.append(
                f"... ({read_result.remaining_due_to_char_limit} more lines truncated due to {max_chars} char limit, "
                f"file has {read_result.total_lines} lines total, use offset/limit to read other parts)"
            )
        elif read_result.remaining_selected_beyond_cap > 0:
            lines_out.append(
                f"... ({read_result.remaining_selected_beyond_cap} more lines truncated due to {line_cap} line limit, "
                f"file has {read_result.total_lines} lines total, use offset/limit to read other parts)"
            )

        read_result_str = "\n".join(lines_out)
        _track_file_access(file_path, content_sha256=read_result.content_sha256)

        return model.ToolResultItem(status="success", output=read_result_str)
