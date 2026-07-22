"""Per-format read handlers for ReadTool.

Each handler reads one file format (text/PDF/notebook/image) and returns a
ToolResultMessage. ReadTool delegates to these so format-specific logic stays
cohesive and isolated from the tool's dispatch/validation code.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
from collections.abc import Callable
from pathlib import Path

from klaude_code.const import (
    READ_MAX_IMAGE_BYTES,
    READ_PARTIAL_PREVIEW_MAX_LINES,
)
from klaude_code.llm.image import detect_mime_type_from_bytes, freeze_image_to_file_for_history
from klaude_code.protocol import message
from klaude_code.protocol.models import ImageUIExtra, ReadPreviewLine, ReadPreviewUIExtra
from klaude_code.tool.core.context import ToolContext
from klaude_code.tool.file._read_core import (
    ReadOptions,
    ReadSegmentResult,
    _format_numbered_line,
    _image_mime_type,
    _read_segment,
    _session_images_dir,
    _track_file_access,
    _truncate_content,
)


async def read_image(
    file_path: str,
    size_bytes: int,
    context: ToolContext,
) -> message.ToolResultMessage:
    """Read a supported image file and snapshot it into session history."""
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
        # Snapshot compression is ~1s of CPU for a multi-MB image; run it in a
        # thread so the event loop (display, spinner, LLM stream) keeps moving.
        image_part = await asyncio.to_thread(
            freeze_image_to_file_for_history,
            message.ImageFilePart(file_path=file_path, mime_type=mime_type),
            images_dir=_session_images_dir(context),
        )
        if image_part is None:
            raise OSError("failed to snapshot image for session history")
    except Exception as exc:
        return message.ToolResultMessage(
            status="error",
            output_text=f"<tool_use_error>Failed to read image file: {exc}</tool_use_error>",
        )

    _track_file_access(context.file_tracker, file_path, content_sha256=hashlib.sha256(image_bytes).hexdigest())
    size_kb = size_bytes / 1024.0 if size_bytes else 0.0
    output_text = f"[image] {Path(file_path).name} ({size_kb:.1f}KB)"
    return message.ToolResultMessage(
        status="success",
        output_text=output_text,
        parts=[image_part],
        ui_extra=ImageUIExtra(file_path=file_path),
    )


async def read_pdf(
    file_path: str,
    context: ToolContext,
    max_chars: int | None,
) -> message.ToolResultMessage:
    """Read a PDF using pdfplumber if available, otherwise return a helpful error."""
    try:
        import pdfplumber  # type: ignore[import-untyped]  # ty: ignore[unresolved-import]  # optional dependency
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

    content, truncated = _truncate_content(content, max_chars)

    _track_file_access(context.file_tracker, file_path)
    header = f"[PDF] {Path(file_path).name}"
    suffix = "\n\n... (content truncated due to size limit)" if truncated else ""
    return message.ToolResultMessage(
        status="success",
        output_text=f"{header}\n\n{content}{suffix}",
    )


async def read_notebook(
    file_path: str,
    context: ToolContext,
    max_chars: int | None,
) -> message.ToolResultMessage:
    """Read a Jupyter notebook (.ipynb) and return cells as structured text."""

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

    content, truncated = _truncate_content(content, max_chars)

    _track_file_access(context.file_tracker, file_path)
    header = f"[Notebook] {Path(file_path).name}"
    suffix = "\n\n... (content truncated due to size limit)" if truncated else ""
    return message.ToolResultMessage(
        status="success",
        output_text=f"{header}\n\n{content}{suffix}",
    )


def _render_segment(
    read_result: ReadSegmentResult,
    *,
    line_cap: int | None,
    max_chars: int | None,
) -> str:
    """Render selected lines plus any truncation footer into the output text."""
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

    return "\n".join(lines_out)


def _build_preview(read_result: ReadSegmentResult, offset: int) -> ReadPreviewUIExtra | None:
    """When reading from the middle of a file, keep the UI preview compact."""
    if offset <= 1:
        return None
    preview_count = READ_PARTIAL_PREVIEW_MAX_LINES
    preview_lines = [
        ReadPreviewLine(line_no=line_no, content=content)
        for line_no, content in read_result.selected_lines[:preview_count]
    ]
    remaining = len(read_result.selected_lines) - len(preview_lines)
    return ReadPreviewUIExtra(lines=preview_lines, remaining_lines=remaining)


async def read_text_file(
    file_path: str,
    context: ToolContext,
    *,
    offset: int,
    limit: int | None,
    char_per_line: int | None,
    line_cap: int | None,
    max_chars: int | None,
    read_text_full: Callable[[str], str],
    missing_file_error: Callable[[str], str],
) -> message.ToolResultMessage:
    """Read a text file segment, render it and track access.

    Dedup and pre-checks remain in ReadTool; this handler owns the actual
    segment read, rendering, caching and tracking once the file is known to
    be a readable text file.
    """
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
            output_text=missing_file_error(file_path),
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

    read_result_str = _render_segment(read_result, line_cap=line_cap, max_chars=max_chars)

    # Cache raw content for external-change diff (only complete, non-truncated reads)
    cached_content = None
    if is_full_read and read_result.remaining_due_to_char_limit == 0 and read_result.remaining_selected_beyond_cap == 0:
        with contextlib.suppress(OSError):
            cached_content = read_text_full(file_path)
    _track_file_access(
        context.file_tracker,
        file_path,
        content_sha256=read_result.content_sha256,
        cached_content=cached_content,
        read_complete=is_full_read,
    )

    ui_extra = _build_preview(read_result, offset)
    return message.ToolResultMessage(status="success", output_text=read_result_str, ui_extra=ui_extra)
