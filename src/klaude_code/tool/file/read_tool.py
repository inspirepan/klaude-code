from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError

from klaude_code.const import (
    BINARY_CHECK_SIZE,
    READ_CHAR_LIMIT_PER_LINE,
    READ_GLOBAL_LINE_CAP,
    READ_MAX_CHARS,
)
from klaude_code.log import log_debug
from klaude_code.prompts.messages import FILE_UNCHANGED_STUB
from klaude_code.protocol import llm_param, message, tools
from klaude_code.tool.core.abc import ToolABC, load_desc
from klaude_code.tool.core.context import ToolContext
from klaude_code.tool.core.registry import register
from klaude_code.tool.file import read_handlers
from klaude_code.tool.file._read_core import _is_supported_image_file
from klaude_code.tool.file._utils import file_exists, is_blocked_device_path, is_directory, read_text


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
        except (ValidationError, ValueError) as e:
            # Pydantic raises ValidationError; malformed JSON surfaces as ValueError
            log_debug(f"ReadTool: invalid arguments: {e}")
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
            return await read_handlers.read_pdf(file_path, context, max_chars)

        # --- Notebook (.ipynb) support ---
        if suffix == ".ipynb":
            return await read_handlers.read_notebook(file_path, context, max_chars)

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
            return await read_handlers.read_image(file_path, size_bytes, context)

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

        return await read_handlers.read_text_file(
            file_path,
            context,
            offset=offset,
            limit=limit,
            char_per_line=char_per_line,
            line_cap=line_cap,
            max_chars=max_chars,
            read_text_full=read_text,
            missing_file_error=_missing_file_error,
        )
