from __future__ import annotations

import asyncio
import contextlib
import os
from pathlib import Path

from pydantic import BaseModel

from klaude_code.core.tool.file._utils import file_exists, hash_text_sha256, is_directory, read_text, write_text
from klaude_code.core.tool.file.diff_builder import build_structured_diff
from klaude_code.core.tool.tool_abc import ToolABC, load_desc
from klaude_code.core.tool.tool_context import get_current_file_tracker
from klaude_code.core.tool.tool_registry import register
from klaude_code.protocol import llm_param, model, tools


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
    async def call(cls, arguments: str) -> model.ToolResultItem:
        try:
            args = WriteArguments.model_validate_json(arguments)
        except ValueError as e:  # pragma: no cover - defensive
            return model.ToolResultItem(status="error", output=f"Invalid arguments: {e}")

        file_path = os.path.abspath(args.file_path)

        if is_directory(file_path):
            return model.ToolResultItem(
                status="error",
                output="<tool_use_error>Illegal operation on a directory. write</tool_use_error>",
            )

        file_tracker = get_current_file_tracker()
        exists = file_exists(file_path)
        tracked_status: model.FileStatus | None = None

        if exists:
            tracked_status = file_tracker.get(file_path) if file_tracker is not None else None
            if tracked_status is None:
                return model.ToolResultItem(
                    status="error",
                    output=("File has not been read yet. Read it first before writing to it."),
                )

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
                    return model.ToolResultItem(
                        status="error",
                        output=(
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
                    return model.ToolResultItem(
                        status="error",
                        output=(
                            "File has been modified externally. Either by user or a linter. "
                            "Read it first before writing to it."
                        ),
                    )

        try:
            await asyncio.to_thread(write_text, file_path, args.content)
        except (OSError, UnicodeError) as e:  # pragma: no cover
            return model.ToolResultItem(status="error", output=f"<tool_use_error>{e}</tool_use_error>")

        if file_tracker is not None:
            with contextlib.suppress(Exception):
                existing = file_tracker.get(file_path)
                is_mem = existing.is_memory if existing else False
                file_tracker[file_path] = model.FileStatus(
                    mtime=Path(file_path).stat().st_mtime,
                    content_sha256=hash_text_sha256(args.content),
                    is_memory=is_mem,
                )

        # For markdown files, use MarkdownDocUIExtra to render content as markdown
        # Otherwise, build diff between previous and new content
        ui_extra: model.ToolResultUIExtra | None
        if file_path.endswith(".md"):
            ui_extra = model.MarkdownDocUIExtra(file_path=file_path, content=args.content)
        else:
            ui_extra = build_structured_diff(before, args.content, file_path=file_path)

        message = f"File {'overwritten' if exists else 'created'} successfully at: {file_path}"
        return model.ToolResultItem(status="success", output=message, ui_extra=ui_extra)
