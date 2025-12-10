from __future__ import annotations

import asyncio
import contextlib
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


@dataclass
class ReadSegmentResult:
    total_lines: int
    selected_lines: list[tuple[int, str]]
    selected_chars_count: int
    remaining_selected_beyond_cap: int
    # For large file diagnostics: list of (start_line, end_line, char_count)
    segment_char_stats: list[tuple[int, int, int]]


def _read_segment(options: ReadOptions) -> ReadSegmentResult:
    total_lines = 0
    selected_lines_count = 0
    remaining_selected_beyond_cap = 0
    selected_lines: list[tuple[int, str]] = []
    selected_chars = 0

    # Track char counts per 100-line segment for diagnostics
    segment_size = 100
    segment_char_stats: list[tuple[int, int, int]] = []
    current_segment_start = options.offset
    current_segment_chars = 0

    with open(options.file_path, encoding="utf-8", errors="replace") as f:
        for line_no, raw_line in enumerate(f, start=1):
            total_lines = line_no
            within = line_no >= options.offset and (options.limit is None or selected_lines_count < options.limit)
            if not within:
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
            current_segment_chars += line_chars

            # Check if we've completed a segment
            if selected_lines_count % segment_size == 0:
                segment_char_stats.append((current_segment_start, line_no, current_segment_chars))
                current_segment_start = line_no + 1
                current_segment_chars = 0

            if options.global_line_cap is None or len(selected_lines) < options.global_line_cap:
                selected_lines.append((line_no, content))
            else:
                remaining_selected_beyond_cap += 1

    # Add the last partial segment if any
    if current_segment_chars > 0 and selected_lines_count > 0:
        last_line = options.offset + selected_lines_count - 1
        segment_char_stats.append((current_segment_start, last_line, current_segment_chars))

    return ReadSegmentResult(
        total_lines=total_lines,
        selected_lines=selected_lines,
        selected_chars_count=selected_chars,
        remaining_selected_beyond_cap=remaining_selected_beyond_cap,
        segment_char_stats=segment_char_stats,
    )


def _track_file_access(file_path: str) -> None:
    file_tracker = get_current_file_tracker()
    if file_tracker is None or not file_exists(file_path) or is_directory(file_path):
        return
    with contextlib.suppress(Exception):
        file_tracker[file_path] = Path(file_path).stat().st_mtime


def _is_supported_image_file(file_path: str) -> bool:
    return Path(file_path).suffix.lower() in _IMAGE_MIME_TYPES


def _image_mime_type(file_path: str) -> str:
    suffix = Path(file_path).suffix.lower()
    mime_type = _IMAGE_MIME_TYPES.get(suffix)
    if mime_type is None:
        raise ValueError(f"Unsupported image file extension: {suffix}")
    return mime_type


def _encode_image_to_data_url(file_path: str, mime_type: str) -> str:
    with open(file_path, "rb") as image_file:
        encoded = b64encode(image_file.read()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


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
    def _effective_limits(cls) -> tuple[int | None, int | None, int | None, int | None]:
        """Return effective limits based on current policy: char_per_line, global_line_cap, max_chars, max_kb"""
        return (
            const.READ_CHAR_LIMIT_PER_LINE,
            const.READ_GLOBAL_LINE_CAP,
            const.READ_MAX_CHARS,
            const.READ_MAX_KB,
        )

    @classmethod
    async def call_with_args(cls, args: ReadTool.ReadArguments) -> model.ToolResultItem:
        # Accept relative path by resolving to absolute (schema encourages absolute)
        file_path = os.path.abspath(args.file_path)

        # Get effective limits based on policy
        char_per_line, line_cap, max_chars, max_kb = cls._effective_limits()

        # Common file errors
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
                    "<tool_use_error>PDF files are not supported by this tool. "
                    "Please use a Python script with `pdfplumber` to extract text/tables:\n\n"
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

        # If file is too large and no pagination provided (only check if limits are enabled)
        try:
            size_bytes = Path(file_path).stat().st_size
        except OSError:
            # Best-effort size detection; on stat errors fall back to treating size as unknown.
            size_bytes = 0

        is_image_file = _is_supported_image_file(file_path)
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
                data_url = _encode_image_to_data_url(file_path, mime_type)
            except Exception as exc:
                return model.ToolResultItem(
                    status="error",
                    output=f"<tool_use_error>Failed to read image file: {exc}</tool_use_error>",
                )

            _track_file_access(file_path)
            size_kb = size_bytes / 1024.0 if size_bytes else 0.0
            output_text = f"[image] {Path(file_path).name} ({size_kb:.1f}KB)"
            image_part = model.ImageURLPart(image_url=model.ImageURLPart.ImageURL(url=data_url, id=None))
            return model.ToolResultItem(status="success", output=output_text, images=[image_part])

        if (
            not is_image_file
            and max_kb is not None
            and args.offset is None
            and args.limit is None
            and size_bytes > max_kb * 1024
        ):
            size_kb = size_bytes / 1024.0
            return model.ToolResultItem(
                status="error",
                output=(
                    f"File content ({size_kb:.1f}KB) exceeds maximum allowed size ({max_kb}KB). Please use offset and limit parameters to read specific portions of the file, or use the `rg` command to search for specific content."
                ),
            )

        offset = 1 if args.offset is None or args.offset < 1 else int(args.offset)
        limit = None if args.limit is None else int(args.limit)
        if limit is not None and limit < 0:
            limit = 0

        # Stream file line-by-line and build response
        read_result: ReadSegmentResult | None = None

        try:
            read_result = await asyncio.to_thread(
                _read_segment,
                ReadOptions(
                    file_path=file_path,
                    offset=offset,
                    limit=limit,
                    char_limit_per_line=char_per_line,
                    global_line_cap=line_cap,
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

        # If offset beyond total lines, emit system reminder warning
        if offset > max(read_result.total_lines, 0):
            warn = f"<system-reminder>Warning: the file exists but is shorter than the provided offset ({offset}). The file has {read_result.total_lines} lines.</system-reminder>"
            # Update FileTracker (we still consider it as a read attempt)
            _track_file_access(file_path)
            return model.ToolResultItem(status="success", output=warn)

        # After limit/offset, if total selected chars exceed limit, error (only check if limits are enabled)
        if max_chars is not None and read_result.selected_chars_count > max_chars:
            # Build segment statistics for better guidance
            stats_lines: list[str] = []
            for start, end, chars in read_result.segment_char_stats:
                stats_lines.append(f"  Lines {start}-{end}: {chars} chars")
            segment_stats_str = "\n".join(stats_lines) if stats_lines else "  (no segment data)"

            return model.ToolResultItem(
                status="error",
                output=(
                    f"Selected file content {read_result.selected_chars_count} chars exceeds maximum allowed chars ({max_chars}).\n"
                    f"File has {read_result.total_lines} total lines.\n\n"
                    f"Character distribution by segment:\n{segment_stats_str}\n\n"
                    f"Use offset and limit parameters to read specific portions. "
                    f"For example: offset=1, limit=100 to read the first 100 lines. "
                    f"Or use `rg` command to search for specific content."
                ),
            )

        # Build display with numbering and reminders
        lines_out: list[str] = [_format_numbered_line(no, content) for no, content in read_result.selected_lines]
        if read_result.remaining_selected_beyond_cap > 0:
            lines_out.append(f"... (more {read_result.remaining_selected_beyond_cap} lines are truncated)")
        read_result_str = "\n".join(lines_out)

        # Update FileTracker with last modified time
        _track_file_access(file_path)

        return model.ToolResultItem(status="success", output=read_result_str)
