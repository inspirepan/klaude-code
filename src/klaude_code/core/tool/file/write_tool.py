from __future__ import annotations

import asyncio
import contextlib
import os
from pathlib import Path

from pydantic import BaseModel

from klaude_code.const import EDIT_MAX_FILE_SIZE
from klaude_code.core.tool.context import ToolContext
from klaude_code.core.tool.file._utils import (
    detect_encoding,
    file_exists,
    hash_text_sha256,
    is_directory,
    read_text,
    write_text,
)
from klaude_code.core.tool.file.diff_builder import build_structured_diff, build_structured_file_diff
from klaude_code.core.tool.tool_abc import ToolABC, load_desc
from klaude_code.core.tool.tool_registry import register
from klaude_code.protocol import llm_param, message, model, tools


class WriteArguments(BaseModel):
    file_path: str
    content: str


@register(tools.WRITE)
class WriteTool(ToolABC):
    @classmethod
    def schema(cls) -> llm_param.ToolSchema:
        return llm_param.ToolSchema(
            name=tools.WRITE,
            type="function",
            description=load_desc(Path(__file__).parent / "write_tool.md"),
            parameters={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "The absolute path to the file to write (must be absolute, not relative)",
                    },
                    "content": {
                        "type": "string",
                        "description": "The content to write to the file",
                    },
                },
                "required": ["file_path", "content"],
                "additionalProperties": False,
            },
        )

    @classmethod
    async def call(cls, arguments: str, context: ToolContext) -> message.ToolResultMessage:
        try:
            args = WriteArguments.model_validate_json(arguments)
        except ValueError as e:  # pragma: no cover - defensive
            return message.ToolResultMessage(status="error", output_text=f"Invalid arguments: {e}")

        file_path = os.path.abspath(args.file_path)

        if is_directory(file_path):
            return message.ToolResultMessage(
                status="error",
                output_text="<tool_use_error>Illegal operation on a directory: write</tool_use_error>",
            )

        file_tracker = context.file_tracker
        exists = file_exists(file_path)
        tracked_status: model.FileStatus | None = None

        if exists:
            # OOM guard: reject files larger than EDIT_MAX_FILE_SIZE
            try:
                file_size = Path(file_path).stat().st_size
            except OSError:
                file_size = 0
            if file_size > EDIT_MAX_FILE_SIZE:
                size_mb = file_size / (1024 * 1024)
                limit_mb = EDIT_MAX_FILE_SIZE / (1024 * 1024)
                return message.ToolResultMessage(
                    status="error",
                    output_text=f"<tool_use_error>File is too large to overwrite ({size_mb:.0f}MB). Maximum file size is {limit_mb:.0f}MB.</tool_use_error>",
                )

            tracked_status = file_tracker.get(file_path)
            if tracked_status is None:
                return message.ToolResultMessage(
                    status="error",
                    output_text=("File has not been read yet. Read it first before writing to it."),
                )

        # Detect encoding of existing file to preserve it on write
        file_encoding = detect_encoding(file_path) if exists else "utf-8"

        # Capture previous content (if any) for diff generation and external-change detection.
        before = ""
        before_read_ok = False
        if exists:
            try:
                before = await asyncio.to_thread(read_text, file_path)
                before_read_ok = True
            except OSError:
                before = ""
                before_read_ok = False

            # Re-check external modifications using content hash when available.
            if before_read_ok and tracked_status is not None and tracked_status.content_sha256 is not None:
                current_sha256 = hash_text_sha256(before)
                if current_sha256 != tracked_status.content_sha256:
                    return message.ToolResultMessage(
                        status="error",
                        output_text=(
                            "File has been modified externally. Either by user or a linter. "
                            "Read it first before writing to it."
                        ),
                    )
            elif tracked_status is not None:
                # Backward-compat: old sessions only stored mtime, or we couldn't hash.
                try:
                    current_mtime = Path(file_path).stat().st_mtime
                except OSError:
                    current_mtime = tracked_status.mtime
                if current_mtime != tracked_status.mtime:
                    return message.ToolResultMessage(
                        status="error",
                        output_text=(
                            "File has been modified externally. Either by user or a linter. "
                            "Read it first before writing to it."
                        ),
                    )

        try:
            await asyncio.to_thread(write_text, file_path, args.content, file_encoding)
        except (OSError, UnicodeError) as e:  # pragma: no cover
            return message.ToolResultMessage(status="error", output_text=f"<tool_use_error>{e}</tool_use_error>")

        with contextlib.suppress(Exception):
            existing = file_tracker.get(file_path)
            is_mem = existing.is_memory if existing else False
            is_skill = existing.is_skill if existing else False
            is_dir = existing.is_directory if existing else False
            file_tracker[file_path] = model.FileStatus(
                mtime=Path(file_path).stat().st_mtime,
                content_sha256=hash_text_sha256(args.content),
                is_memory=is_mem,
                is_skill=is_skill,
                skill_attachment_source=None,
                is_directory=is_dir,
            )

        file_diff = build_structured_file_diff(before, args.content, file_path=file_path)
        if context.file_change_summary is not None:
            if exists:
                context.file_change_summary.record_edited(file_path)
            else:
                context.file_change_summary.record_created(file_path)
            context.file_change_summary.add_diff(
                added=file_diff.stats_add,
                removed=file_diff.stats_remove,
                path=file_path,
            )

        # For markdown files, use MarkdownDocUIExtra to render content as markdown
        # Otherwise, build diff between previous and new content
        ui_extra: model.ToolResultUIExtra | None
        if file_path.endswith(".md") and not exists:
            ui_extra = model.MarkdownDocUIExtra(file_path=file_path, content=args.content)
        else:
            ui_extra = build_structured_diff(before, args.content, file_path=file_path)

        if exists:
            output_msg = f"The file {file_path} has been updated successfully."
        else:
            output_msg = f"File created successfully at: {file_path}"
        return message.ToolResultMessage(status="success", output_text=output_msg, ui_extra=ui_extra)
