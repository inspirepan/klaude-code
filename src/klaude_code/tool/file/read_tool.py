from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import os
from base64 import b64encode
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, Field

from klaude_code.const import (
    BINARY_CHECK_SIZE,
    FILE_UNCHANGED_STUB,
    READ_CHAR_LIMIT_PER_LINE,
    READ_GLOBAL_LINE_CAP,
    READ_MAX_CHARS,
    READ_MAX_IMAGE_BYTES,
)
from klaude_code.llm.image import detect_mime_type_from_bytes
from klaude_code.protocol import llm_param, message, model, tools
from klaude_code.protocol.model import ImageUIExtra, ReadPreviewLine, ReadPreviewUIExtra
from klaude_code.tool.context import FileTracker, ToolContext
from klaude_code.tool.file._utils import detect_encoding, file_exists, is_blocked_device_path, is_directory, read_text
from klaude_code.tool.tool_abc import ToolABC, load_desc
from klaude_code.tool.tool_registry import register

_IMAGE_MIME_TYPES: dict[str, str] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}


def _is_binary_file(file_path: str) -> bool:
    """Check if a file is binary by looking for null bytes in the first chunk.

    Excludes files with a UTF-16LE BOM (FF FE) since they legitimately contain null bytes.
    """
    try:
        with open(file_path, "rb") as f:
            chunk = f.read(BINARY_CHECK_SIZE)
            # UTF-16LE BOM: legitimate text encoding that contains null bytes
            if len(chunk) >= 2 and chunk[0] == 0xFF and chunk[1] == 0xFE:
                return False
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
        file_tracker[file_path] = model.FileStatus(
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


def _missing_file_directory_candidate(file_path: str) -> str | None:
    directory = os.path.dirname(file_path)
    stem = Path(file_path).stem
    if not directory or not stem:
        return None

    candidate = os.path.join(directory, stem)
    return candidate if is_directory(candidate) else None


def _directory_file_preview(
    directory_path: str,
    file_path: str,
    *,
    max_suggestions: int = 5,
) -> tuple[list[str], int]:
    try:
        entries = sorted(os.listdir(directory_path), key=str.lower)
    except OSError:
        return [], 0

    requested_name = os.path.basename(file_path).lower()
    requested_stem = Path(file_path).stem.lower()

    init_files: list[str] = []
    exact_name_files: list[str] = []
    stem_match_files: list[str] = []
    python_files: list[str] = []
    other_files: list[str] = []

    for entry in entries:
        entry_path = os.path.join(directory_path, entry)
        if is_directory(entry_path):
            continue

        entry_lower = entry.lower()
        if entry_lower == "__init__.py":
            init_files.append(entry_path)
        elif entry_lower == requested_name:
            exact_name_files.append(entry_path)
        elif requested_stem and requested_stem in entry_lower:
            stem_match_files.append(entry_path)
        elif entry_lower.endswith(".py"):
            python_files.append(entry_path)
        else:
            other_files.append(entry_path)

    ranked_files = init_files + exact_name_files + stem_match_files + python_files + other_files
    preview = ranked_files[:max_suggestions]
    remaining = max(0, len(ranked_files) - len(preview))
    return preview, remaining


def _missing_file_error(file_path: str) -> str:
    directory_candidate = _missing_file_directory_candidate(file_path)

    if directory_candidate is None:
        return "<tool_use_error>File does not exist.</tool_use_error>"

    message_lines = [
        "File not found:",
        file_path,
        "",
        "Did you mean one of these?",
        f"- {directory_candidate} (directory)",
    ]
    preview_files, remaining_count = _directory_file_preview(directory_candidate, file_path)
    message_lines.extend(f"- {path}" for path in preview_files)
    if remaining_count > 0:
        message_lines.append(f"(+{remaining_count} more files; use Bash ls for full listing)")
    message_lines.append("\nNote: Read cannot open directories. Use Bash `ls` or `tree` to browse.")

    return f"<tool_use_error>{'\n'.join(message_lines)}</tool_use_error>"


def _truncate_content(content: str, max_chars: int | None) -> tuple[str, bool]:
    """Truncate content to max_chars, returning (content, was_truncated)."""
    if max_chars is None or len(content) <= max_chars:
        return content, False
    return content[:max_chars], True


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
            description=load_desc(
                Path(__file__).parent / "read_tool.md",
                {
                    "line_cap": str(READ_GLOBAL_LINE_CAP),
                    "char_limit_per_line": str(READ_CHAR_LIMIT_PER_LINE),
                    "max_chars": str(READ_MAX_CHARS),
                },
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
    async def call(cls, arguments: str, context: ToolContext) -> message.ToolResultMessage:
        try:
            args = ReadTool.ReadArguments.model_validate_json(arguments)
        except Exception as e:  # pragma: no cover - defensive
            return message.ToolResultMessage(status="error", output_text=f"Invalid arguments: {e}")
        return await cls.call_with_args(args, context)

    @classmethod
    def _effective_limits(cls) -> tuple[int | None, int | None, int | None]:
        return (
            READ_CHAR_LIMIT_PER_LINE,
            READ_GLOBAL_LINE_CAP,
            READ_MAX_CHARS,
        )

    @classmethod
    async def call_with_args(cls, args: ReadTool.ReadArguments, context: ToolContext) -> message.ToolResultMessage:
        file_path = os.path.abspath(args.file_path)
        char_per_line, line_cap, max_chars = cls._effective_limits()

        if is_directory(file_path):
            return message.ToolResultMessage(
                status="error",
                output_text="<tool_use_error>Illegal operation on a directory: read</tool_use_error>",
            )

        # Block dangerous device paths that would hang the process
        if is_blocked_device_path(file_path):
            return message.ToolResultMessage(
                status="error",
                output_text=f"<tool_use_error>Cannot read '{file_path}': this device file would block or produce infinite output.</tool_use_error>",
            )

        if not file_exists(file_path):
            return message.ToolResultMessage(
                status="error",
                output_text=_missing_file_error(file_path),
            )

        suffix = Path(file_path).suffix.lower()

        # --- PDF support ---
        if suffix == ".pdf":
            return await cls._read_pdf(file_path, context)

        # --- Notebook (.ipynb) support ---
        if suffix == ".ipynb":
            return await cls._read_notebook(file_path, context)

        is_image_file = _is_supported_image_file(file_path)
        # Check for binary files (skip for images which are handled separately)
        if not is_image_file and _is_binary_file(file_path):
            return message.ToolResultMessage(
                status="error",
                output_text=(
                    "<tool_use_error>This appears to be a binary file and cannot be read as text. "
                    "Use appropriate tools or libraries to handle binary files.</tool_use_error>"
                ),
            )

        try:
            size_bytes = Path(file_path).stat().st_size
        except OSError:
            size_bytes = 0

        if is_image_file:
            return await cls._read_image(file_path, size_bytes, context)

        # --- Read dedup: avoid resending unchanged content ---
        offset = 1 if args.offset is None or args.offset < 1 else args.offset
        limit = args.limit
        if limit is not None and limit < 0:
            limit = 0

        # Read dedup: only for files previously fully read by ReadTool (not just tracked by Edit/Write)
        existing_status = context.file_tracker.get(file_path) if context.file_tracker else None
        if (
            existing_status is not None
            and existing_status.read_complete
            and existing_status.content_sha256 is not None
            and offset == 1
            and limit is None
        ):
            try:
                current_mtime = Path(file_path).stat().st_mtime
                if current_mtime == existing_status.mtime:
                    return message.ToolResultMessage(status="success", output_text=FILE_UNCHANGED_STUB)
            except OSError:
                pass

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
            return message.ToolResultMessage(
                status="error",
                output_text=_missing_file_error(file_path),
            )
        except IsADirectoryError:
            return message.ToolResultMessage(
                status="error",
                output_text="<tool_use_error>Illegal operation on a directory: read</tool_use_error>",
            )

        is_full_read = offset == 1 and limit is None
        if offset > max(read_result.total_lines, 0):
            warn = f"<system-reminder>Warning: the file exists but is shorter than the provided offset ({offset}). The file has {read_result.total_lines} lines.</system-reminder>"
            _track_file_access(
                context.file_tracker, file_path, content_sha256=read_result.content_sha256, read_complete=is_full_read
            )
            return message.ToolResultMessage(status="success", output_text=warn)

        lines_out: list[str] = [_format_numbered_line(no, content) for no, content in read_result.selected_lines]

        # Show truncation info with reason
        if read_result.remaining_due_to_char_limit > 0:
            lines_out.append(
                f"… ({read_result.remaining_due_to_char_limit} more lines truncated due to {max_chars} char limit, "
                f"file has {read_result.total_lines} lines total, use offset/limit to read other parts)"
            )
        elif read_result.remaining_selected_beyond_cap > 0:
            lines_out.append(
                f"… ({read_result.remaining_selected_beyond_cap} more lines truncated due to {line_cap} line limit, "
                f"file has {read_result.total_lines} lines total, use offset/limit to read other parts)"
            )

        read_result_str = "\n".join(lines_out)
        # Cache raw content for external-change diff (only complete, non-truncated reads)
        cached_content = None
        if (
            is_full_read
            and read_result.remaining_due_to_char_limit == 0
            and read_result.remaining_selected_beyond_cap == 0
        ):
            with contextlib.suppress(OSError):
                cached_content = read_text(file_path)
        _track_file_access(
            context.file_tracker,
            file_path,
            content_sha256=read_result.content_sha256,
            cached_content=cached_content,
            read_complete=is_full_read,
        )

        # When offset > 1, show a preview of the first 5 lines in UI
        ui_extra = None
        if args.offset is not None and args.offset > 1:
            preview_count = 5
            preview_lines = [
                ReadPreviewLine(line_no=line_no, content=content)
                for line_no, content in read_result.selected_lines[:preview_count]
            ]
            remaining = len(read_result.selected_lines) - len(preview_lines)
            ui_extra = ReadPreviewUIExtra(lines=preview_lines, remaining_lines=remaining)

        return message.ToolResultMessage(status="success", output_text=read_result_str, ui_extra=ui_extra)

    @classmethod
    async def _read_image(cls, file_path: str, size_bytes: int, context: ToolContext) -> message.ToolResultMessage:
        if size_bytes > READ_MAX_IMAGE_BYTES:
            size_mb = size_bytes / (1024 * 1024)
            limit_mb = READ_MAX_IMAGE_BYTES / (1024 * 1024)
            return message.ToolResultMessage(
                status="error",
                output_text=(
                    f"<tool_use_error>Image size ({size_mb:.2f}MB) exceeds maximum supported size ({limit_mb:.2f}MB) for inline transfer.</tool_use_error>"
                ),
            )
        try:
            mime_type = _image_mime_type(file_path)
            with open(file_path, "rb") as image_file:
                image_bytes = image_file.read()
            # Correct MIME type if magic bytes disagree with extension
            detected = detect_mime_type_from_bytes(image_bytes)
            if detected:
                mime_type = detected
            # Note: downstream LLM input layer calls normalize_image_data_url()
            # which handles resize/compression, so we don't resize here.
            data_url = f"data:{mime_type};base64,{b64encode(image_bytes).decode('ascii')}"
        except Exception as exc:
            return message.ToolResultMessage(
                status="error",
                output_text=f"<tool_use_error>Failed to read image file: {exc}</tool_use_error>",
            )

        _track_file_access(context.file_tracker, file_path, content_sha256=hashlib.sha256(image_bytes).hexdigest())
        size_kb = size_bytes / 1024.0 if size_bytes else 0.0
        output_text = f"[image] {Path(file_path).name} ({size_kb:.1f}KB)"
        image_part = message.ImageURLPart(url=data_url, id=None)
        return message.ToolResultMessage(
            status="success",
            output_text=output_text,
            parts=[image_part],
            ui_extra=ImageUIExtra(file_path=file_path),
        )

    @classmethod
    async def _read_pdf(cls, file_path: str, context: ToolContext) -> message.ToolResultMessage:
        """Read PDF file using pdfplumber if available, otherwise return helpful error."""
        try:
            import pdfplumber  # type: ignore[import-untyped]
        except ImportError:
            return message.ToolResultMessage(
                status="error",
                output_text=(
                    "<tool_use_error>PDF files require pdfplumber. Install with: uv add pdfplumber\n"
                    "Or use a Python script:\n\n"
                    "```python\n"
                    "# /// script\n"
                    '# dependencies = ["pdfplumber"]\n'
                    "# ///\n"
                    "import pdfplumber\n\n"
                    f"with pdfplumber.open('{file_path}') as pdf:\n"
                    "    for page in pdf.pages:\n"
                    "        print(page.extract_text())\n"
                    "```\n"
                    "</tool_use_error>"
                ),
            )

        def _extract() -> str:
            pages_text: list[str] = []
            with pdfplumber.open(file_path) as pdf:  # pyright: ignore[reportUnknownMemberType,reportUnknownVariableType]
                for i, page in enumerate(pdf.pages, 1):  # pyright: ignore[reportUnknownMemberType,reportUnknownVariableType,reportUnknownArgumentType]
                    text: str = page.extract_text() or ""  # pyright: ignore[reportUnknownMemberType,reportUnknownVariableType]
                    pages_text.append(f"--- Page {i} ---\n{text}")
            return "\n\n".join(pages_text)

        try:
            content = await asyncio.to_thread(_extract)
        except Exception as exc:
            return message.ToolResultMessage(
                status="error",
                output_text=f"<tool_use_error>Failed to read PDF: {exc}</tool_use_error>",
            )

        _, _, max_chars = cls._effective_limits()
        content, truncated = _truncate_content(content, max_chars)

        _track_file_access(context.file_tracker, file_path)
        header = f"[PDF] {Path(file_path).name}"
        suffix = "\n\n... (content truncated due to size limit)" if truncated else ""
        return message.ToolResultMessage(
            status="success",
            output_text=f"{header}\n\n{content}{suffix}",
        )

    @classmethod
    async def _read_notebook(cls, file_path: str, context: ToolContext) -> message.ToolResultMessage:
        """Read Jupyter notebook (.ipynb) and return cells as structured text."""

        def _parse() -> str:
            with open(file_path, encoding="utf-8") as f:
                nb = json.load(f)
            cells = nb.get("cells", [])
            parts: list[str] = []
            for i, cell in enumerate(cells, 1):
                cell_type = cell.get("cell_type", "unknown")
                source = "".join(cell.get("source", []))
                header = f"--- Cell {i} [{cell_type}] ---"
                parts.append(f"{header}\n{source}")
                # Include text outputs for code cells
                outputs = cell.get("outputs", [])
                for output in outputs:
                    if "text" in output:
                        text = "".join(output["text"])
                        parts.append(f"[output]\n{text}")
                    elif "data" in output and "text/plain" in output["data"]:
                        text = "".join(output["data"]["text/plain"])
                        parts.append(f"[output]\n{text}")
            return "\n\n".join(parts)

        try:
            content = await asyncio.to_thread(_parse)
        except Exception as exc:
            return message.ToolResultMessage(
                status="error",
                output_text=f"<tool_use_error>Failed to read notebook: {exc}</tool_use_error>",
            )

        _, _, max_chars = cls._effective_limits()
        content, truncated = _truncate_content(content, max_chars)

        _track_file_access(context.file_tracker, file_path)
        header = f"[Notebook] {Path(file_path).name}"
        suffix = "\n\n... (content truncated due to size limit)" if truncated else ""
        return message.ToolResultMessage(
            status="success",
            output_text=f"{header}\n\n{content}{suffix}",
        )
