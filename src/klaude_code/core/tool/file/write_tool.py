from __future__ import annotations

import asyncio
import contextlib
import difflib
import os
from pathlib import Path

from pydantic import BaseModel

from klaude_code.core.tool.file._utils import file_exists, is_directory, read_text, write_text
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
        except Exception as e:  # pragma: no cover - defensive
            return model.ToolResultItem(status="error", output=f"Invalid arguments: {e}")

        file_path = os.path.abspath(args.file_path)

        if is_directory(file_path):
            return model.ToolResultItem(
                status="error",
                output="<tool_use_error>Illegal operation on a directory. write</tool_use_error>",
            )

        file_tracker = get_current_file_tracker()
        exists = file_exists(file_path)

        if exists:
            tracked_mtime: float | None = None
            if file_tracker is not None:
                tracked_mtime = file_tracker.get(file_path)
            if tracked_mtime is None:
                return model.ToolResultItem(
                    status="error",
                    output=("File has not been read yet. Read it first before writing to it."),
                )
            try:
                current_mtime = Path(file_path).stat().st_mtime
            except Exception:
                current_mtime = tracked_mtime
            if current_mtime != tracked_mtime:
                return model.ToolResultItem(
                    status="error",
                    output=(
                        "File has been modified externally. Either by user or a linter. "
                        "Read it first before writing to it."
                    ),
                )

        # Capture previous content (if any) for diff generation
        before = ""
        if exists:
            try:
                before = await asyncio.to_thread(read_text, file_path)
            except Exception:
                before = ""

        try:
            await asyncio.to_thread(write_text, file_path, args.content)
        except Exception as e:  # pragma: no cover
            return model.ToolResultItem(status="error", output=f"<tool_use_error>{e}</tool_use_error>")

        if file_tracker is not None:
            with contextlib.suppress(Exception):
                file_tracker[file_path] = Path(file_path).stat().st_mtime

        # Build diff between previous and new content
        after = args.content
        diff_lines = list(
            difflib.unified_diff(
                before.splitlines(),
                after.splitlines(),
                fromfile=file_path,
                tofile=file_path,
                n=3,
            )
        )
        diff_text = "\n".join(diff_lines)
        ui_extra = model.DiffTextUIExtra(diff_text=diff_text)

        message = f"File {'overwritten' if exists else 'created'} successfully at: {file_path}"
        return model.ToolResultItem(status="success", output=message, ui_extra=ui_extra)
