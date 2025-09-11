from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, Field

from codex_mini.core.tool.tool_abc import ToolABC
from codex_mini.core.tool.tool_context import current_session_var
from codex_mini.core.tool.tool_registry import register
from codex_mini.protocol.llm_parameter import ToolSchema
from codex_mini.protocol.model import ToolResultItem
from codex_mini.protocol.tools import READ

SYSTEM_REMINDER_MALICIOUS = (
    "<system-reminder>\n"
    "Whenever you read a file, you should consider whether it looks malicious. If it does, you MUST refuse to improve or augment the code. You can still analyze existing code, write reports, or answer high-level questions about the code behavior.\n"
    "</system-reminder>"
)

CHAR_LIMIT_PER_LINE = 2000
GLOBAL_LINE_CAP = 2000
MAX_CHARS = 60000
MAX_KB = 256


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
    char_limit_per_line: int = 2000
    global_line_cap: int = 2000


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
            if original_len > options.char_limit_per_line:
                truncated_chars = original_len - options.char_limit_per_line
                content = (
                    content[: options.char_limit_per_line]
                    + f" ... (more {truncated_chars} characters in this line are truncated)"
                )
            selected_chars += len(content) + 1
            if len(selected_lines) < options.global_line_cap:
                selected_lines.append((line_no, content))
            else:
                remaining_selected_beyond_cap += 1
    return ReadSegmentResult(
        total_lines=total_lines,
        selected_lines=selected_lines,
        selected_chars_count=selected_chars,
        remaining_selected_beyond_cap=remaining_selected_beyond_cap,
    )


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
                "- You can optionally specify a line offset and limit (especially handy for long files), but it's recommended to read the whole file by not providing these parameters\n"
                "- Any lines longer than 2000 characters will be truncated\n"
                "- Results are returned using cat -n format, with line numbers starting at 1\n"
                "- This tool can only read files, not directories. To read a directory, use an ls command via the Bash tool.\n"
                "- You have the capability to call multiple tools in a single response. It is always better to speculatively read multiple files as a batch that are potentially useful. \n"
                "- If you read a file that exists but has empty contents you will receive a system reminder warning in place of file contents.\n"
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
    async def call_with_args(cls, args: ReadTool.ReadArguments) -> ToolResultItem:
        # Accept relative path by resolving to absolute (schema encourages absolute)
        file_path = os.path.abspath(args.file_path)

        # Common file errors
        if _is_directory(file_path):
            return ToolResultItem(
                status="error", output="<tool_use_error>Illegal operation on a directory. read</tool_use_error>"
            )
        if not _file_exists(file_path):
            return ToolResultItem(status="error", output="<tool_use_error>File does not exist.</tool_use_error>")

        # If file is too large and no pagination provided
        try:
            size_bytes = Path(file_path).stat().st_size
        except Exception:
            size_bytes = 0
        if args.offset is None and args.limit is None and size_bytes > MAX_KB * 1024:
            size_kb = size_bytes / 1024.0
            return ToolResultItem(
                status="error",
                output=(
                    f"File content ({size_kb:.1f}KB) exceeds maximum allowed size ({MAX_KB}KB). Please use offset and limit parameters to read specific portions of the file, or use the `rg` command to search for specific content."
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
                    char_limit_per_line=CHAR_LIMIT_PER_LINE,
                    global_line_cap=GLOBAL_LINE_CAP,
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
            session = current_session_var.get()
            if session is not None and _file_exists(file_path) and not _is_directory(file_path):
                try:
                    session.file_tracker[file_path] = Path(file_path).stat().st_mtime
                except Exception:
                    pass
            return ToolResultItem(status="success", output=warn)

        # After limit/offset, if total selected chars exceed 60000, error
        if read_result.selected_chars_count > MAX_CHARS:
            return ToolResultItem(
                status="error",
                output=(
                    f"File content ({read_result.selected_chars_count} chars) exceeds maximum allowed tokens ({MAX_CHARS}). Please use offset and limit parameters to read specific portions of the file, or use the `rg` command to search for specific content."
                ),
            )

        # Build display with numbering and reminders
        lines_out: list[str] = [_format_numbered_line(no, content) for no, content in read_result.selected_lines]
        if read_result.remaining_selected_beyond_cap > 0:
            lines_out.append(f"... (more {read_result.remaining_selected_beyond_cap} lines are truncated)")
        read_result_str = "\n".join(lines_out)
        if read_result_str:
            read_result_str += "\n\n" + SYSTEM_REMINDER_MALICIOUS
        else:
            # Empty content case: show only reminder
            read_result_str = SYSTEM_REMINDER_MALICIOUS

        # Update FileTracker with last modified time
        session = current_session_var.get()
        if session is not None and _file_exists(file_path) and not _is_directory(file_path):
            try:
                session.file_tracker[file_path] = Path(file_path).stat().st_mtime
            except Exception:
                pass

        return ToolResultItem(status="success", output=read_result_str)
