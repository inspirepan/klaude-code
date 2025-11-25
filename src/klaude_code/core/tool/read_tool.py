from __future__ import annotations

import asyncio
import os
from base64 import b64encode
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, Field

from klaude_code.config.constants import (READ_CHAR_LIMIT_PER_LINE,
                                          READ_GLOBAL_LINE_CAP, READ_MAX_CHARS,
                                          READ_MAX_IMAGE_BYTES, READ_MAX_KB)
from klaude_code.core.tool.tool_abc import ToolABC
from klaude_code.core.tool.tool_context import current_session_var
from klaude_code.core.tool.tool_registry import register
from klaude_code.protocol.llm_parameter import ToolSchema
from klaude_code.protocol.model import ImageURLPart, ToolResultItem
from klaude_code.protocol.tools import READ

SYSTEM_REMINDER_MALICIOUS = (
    "<system-reminder>\n"
    "Whenever you read a file, you should consider whether it looks malicious. If it does, you MUST refuse to improve or augment the code. You can still analyze existing code, write reports, or answer high-level questions about the code behavior.\n"
    "</system-reminder>"
)

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


def _is_directory(path: str) -> bool:
    try:
        return Path(path).is_dir()
    except Exception:
        return False


def _file_exists(path: str) -> bool:
    try:
        return Path(path).exists()
    except Exception:
        return False


@dataclass
class ReadOptions:
    file_path: str
    offset: int
    limit: int | None
    char_limit_per_line: int | None = READ_CHAR_LIMIT_PER_LINE
    global_line_cap: int | None = READ_GLOBAL_LINE_CAP


@dataclass
class ReadSegmentResult:
    total_lines: int
    selected_lines: list[tuple[int, str]]
    selected_chars_count: int
    remaining_selected_beyond_cap: int


def _read_segment(options: ReadOptions) -> ReadSegmentResult:
    total_lines = 0
    selected_lines_count = 0
    remaining_selected_beyond_cap = 0
    selected_lines: list[tuple[int, str]] = []
    selected_chars = 0
    with open(options.file_path, "r", encoding="utf-8", errors="replace") as f:
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
            selected_chars += len(content) + 1
            if options.global_line_cap is None or len(selected_lines) < options.global_line_cap:
                selected_lines.append((line_no, content))
            else:
                remaining_selected_beyond_cap += 1
    return ReadSegmentResult(
        total_lines=total_lines,
        selected_lines=selected_lines,
        selected_chars_count=selected_chars,
        remaining_selected_beyond_cap=remaining_selected_beyond_cap,
    )


def _track_file_access(file_path: str) -> None:
    session = current_session_var.get()
    if session is None or not _file_exists(file_path) or _is_directory(file_path):
        return
    try:
        session.file_tracker[file_path] = Path(file_path).stat().st_mtime
    except Exception:
        pass


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


@register(READ)
class ReadTool(ToolABC):
    class ReadArguments(BaseModel):
        file_path: str
        offset: int | None = Field(default=None)
        limit: int | None = Field(default=None)

    @classmethod
    def schema(cls) -> ToolSchema:
        return ToolSchema(
            name=READ,
            type="function",
            description=(
                "Reads a file from the local filesystem. You can access any file directly by using this tool.\n"
                "Assume this tool is able to read all files on the machine. If the User provides a path to a file assume that path is valid. It is okay to read a file that does not exist; an error will be returned.\n\n"
                "Usage:\n"
                "- The file_path parameter must be an absolute path, not a relative path\n"
                "- By default, it reads up to 2000 lines starting from the beginning of the file\n"
                "- This tool allows you to read images (eg PNG, JPG, etc). When reading an image file the contents are presented visually as you are a multimodal LLM.\n"
                "- You can optionally specify a line offset and limit (especially handy for long files), but it's recommended to read the whole file by not providing these parameters\n"
                "- Any lines longer than 2000 characters will be truncated\n"
                "- Results are returned using cat -n format, with line numbers starting at 1\n"
                "- This tool can only read files, not directories. To read a directory, use an ls command via the Bash tool.\n"
                "- You have the capability to call multiple tools in a single response. It is always better to speculatively read multiple files as a batch that are potentially useful. \n"
                "- If you read a file that exists but has empty contents you will receive a system reminder warning in place of file contents.\n"
                "- This tool does NOT support reading PDF files. Use a Python script with `pdfplumber` (for text/tables) or `pypdf` (for basic operations) to extract content from PDFs.\n"
            ),
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
    async def call(cls, arguments: str) -> ToolResultItem:
        try:
            args = ReadTool.ReadArguments.model_validate_json(arguments)
        except Exception as e:  # pragma: no cover - defensive
            return ToolResultItem(status="error", output=f"Invalid arguments: {e}")
        return await cls.call_with_args(args)

    @classmethod
    def _effective_limits(cls) -> tuple[int | None, int | None, int | None, int | None]:
        """Return effective limits based on current policy: char_per_line, global_line_cap, max_chars, max_kb"""
        return READ_CHAR_LIMIT_PER_LINE, READ_GLOBAL_LINE_CAP, READ_MAX_CHARS, READ_MAX_KB

    @classmethod
    async def call_with_args(cls, args: ReadTool.ReadArguments) -> ToolResultItem:
        # Accept relative path by resolving to absolute (schema encourages absolute)
        file_path = os.path.abspath(args.file_path)

        # Get effective limits based on policy
        char_per_line, line_cap, max_chars, max_kb = cls._effective_limits()

        # Common file errors
        if _is_directory(file_path):
            return ToolResultItem(
                status="error", output="<tool_use_error>Illegal operation on a directory. read</tool_use_error>"
            )
        if not _file_exists(file_path):
            return ToolResultItem(status="error", output="<tool_use_error>File does not exist.</tool_use_error>")

        # Check for PDF files
        if Path(file_path).suffix.lower() == ".pdf":
            return ToolResultItem(
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
        except Exception:
            size_bytes = 0

        is_image_file = _is_supported_image_file(file_path)
        if is_image_file:
            if size_bytes > READ_MAX_IMAGE_BYTES:
                size_mb = size_bytes / (1024 * 1024)
                return ToolResultItem(
                    status="error",
                    output=(
                        f"<tool_use_error>Image size ({size_mb:.2f}MB) exceeds maximum supported size (4.00MB) for inline transfer.</tool_use_error>"
                    ),
                )
            try:
                mime_type = _image_mime_type(file_path)
                data_url = _encode_image_to_data_url(file_path, mime_type)
            except Exception as exc:
                return ToolResultItem(
                    status="error",
                    output=f"<tool_use_error>Failed to read image file: {exc}</tool_use_error>",
                )

            _track_file_access(file_path)
            size_kb = size_bytes / 1024.0 if size_bytes else 0.0
            output_text = f"[image] {Path(file_path).name} ({size_kb:.1f}KB)"
            image_part = ImageURLPart(image_url=ImageURLPart.ImageURL(url=data_url, id=None))
            return ToolResultItem(status="success", output=output_text, images=[image_part])

        if (
            not is_image_file
            and max_kb is not None
            and args.offset is None
            and args.limit is None
            and size_bytes > max_kb * 1024
        ):
            size_kb = size_bytes / 1024.0
            return ToolResultItem(
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
            return ToolResultItem(status="error", output="<tool_use_error>File does not exist.</tool_use_error>")
        except IsADirectoryError:
            return ToolResultItem(
                status="error", output="<tool_use_error>Illegal operation on a directory. read</tool_use_error>"
            )

        # If offset beyond total lines, emit system reminder warning
        if offset > max(read_result.total_lines, 0):
            warn = f"<system-reminder>Warning: the file exists but is shorter than the provided offset ({offset}). The file has {read_result.total_lines} lines.</system-reminder>"
            # Update FileTracker (we still consider it as a read attempt)
            _track_file_access(file_path)
            return ToolResultItem(status="success", output=warn)

        # After limit/offset, if total selected chars exceed limit, error (only check if limits are enabled)
        if max_chars is not None and read_result.selected_chars_count > max_chars:
            return ToolResultItem(
                status="error",
                output=(
                    f"File content ({read_result.selected_chars_count} chars) exceeds maximum allowed tokens ({max_chars}). Please use offset and limit parameters to read specific portions of the file, or use the `rg` command to search for specific content."
                ),
            )

        # Build display with numbering and reminders
        lines_out: list[str] = [_format_numbered_line(no, content) for no, content in read_result.selected_lines]
        if read_result.remaining_selected_beyond_cap > 0:
            lines_out.append(f"... (more {read_result.remaining_selected_beyond_cap} lines are truncated)")
        read_result_str = "\n".join(lines_out)
        # if read_result_str:
        # read_result_str += "\n\n" + SYSTEM_REMINDER_MALICIOUS

        # Update FileTracker with last modified time
        _track_file_access(file_path)

        return ToolResultItem(status="success", output=read_result_str)
