from __future__ import annotations

import asyncio
import contextlib
import difflib
import os
from pathlib import Path

from pydantic import BaseModel, Field

from klaude_code.core.tool.file._utils import file_exists, is_directory, read_text, write_text
from klaude_code.core.tool.file.edit_tool import EditTool
from klaude_code.core.tool.tool_abc import ToolABC, load_desc
from klaude_code.core.tool.tool_context import get_current_file_tracker
from klaude_code.core.tool.tool_registry import register
from klaude_code.protocol import llm_param, model, tools


@register(tools.MULTI_EDIT)
class MultiEditTool(ToolABC):
    class MultiEditEditItem(BaseModel):
        old_string: str
        new_string: str
        replace_all: bool = Field(default=False)

    class MultiEditArguments(BaseModel):
        file_path: str
        edits: list[MultiEditTool.MultiEditEditItem]

    @classmethod
    def schema(cls) -> llm_param.ToolSchema:
        return llm_param.ToolSchema(
            name=tools.MULTI_EDIT,
            type="function",
            description=load_desc(Path(__file__).parent / "multi_edit_tool.md"),
            parameters={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "The absolute path to the file to modify",
                    },
                    "edits": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "old_string": {
                                    "type": "string",
                                    "description": "The text to replace",
                                },
                                "new_string": {
                                    "type": "string",
                                    "description": "The text to replace it with",
                                },
                                "replace_all": {
                                    "type": "boolean",
                                    "default": False,
                                    "description": "Replace all occurences of old_string (default false).",
                                },
                            },
                            "required": ["old_string", "new_string"],
                            "additionalProperties": False,
                        },
                        "minItems": 1,
                        "description": "Array of edit operations to perform sequentially on the file",
                    },
                },
                "required": ["file_path", "edits"],
                "additionalProperties": False,
            },
        )

    @classmethod
    async def call(cls, arguments: str) -> model.ToolResultItem:
        try:
            args = MultiEditTool.MultiEditArguments.model_validate_json(arguments)
        except Exception as e:  # pragma: no cover - defensive
            return model.ToolResultItem(status="error", output=f"Invalid arguments: {e}")

        file_path = os.path.abspath(args.file_path)

        # Directory error first
        if is_directory(file_path):
            return model.ToolResultItem(
                status="error",
                output="<tool_use_error>Illegal operation on a directory. multi_edit</tool_use_error>",
            )

        file_tracker = get_current_file_tracker()

        # FileTracker check:
        if file_exists(file_path):
            if file_tracker is not None:
                tracked = file_tracker.get(file_path)
                if tracked is None:
                    return model.ToolResultItem(
                        status="error",
                        output=("File has not been read yet. Read it first before writing to it."),
                    )
                try:
                    current_mtime = Path(file_path).stat().st_mtime
                except Exception:
                    current_mtime = tracked
                if current_mtime != tracked:
                    return model.ToolResultItem(
                        status="error",
                        output=(
                            "File has been modified externally. Either by user or a linter. Read it first before writing to it."
                        ),
                    )
        else:
            # Allow creation only if first edit is creating content (old_string == "")
            if not args.edits or args.edits[0].old_string != "":
                return model.ToolResultItem(
                    status="error",
                    output=("File has not been read yet. Read it first before writing to it."),
                )

        # Load initial content (empty for new file case)
        if file_exists(file_path):
            before = await asyncio.to_thread(read_text, file_path)
        else:
            before = ""

        # Validate all edits atomically against staged content
        staged = before
        for edit in args.edits:
            err = EditTool.valid(
                content=staged,
                old_string=edit.old_string,
                new_string=edit.new_string,
                replace_all=edit.replace_all,
            )
            if err is not None:
                return model.ToolResultItem(status="error", output=err)
            # Apply to staged content
            staged = EditTool.execute(
                content=staged,
                old_string=edit.old_string,
                new_string=edit.new_string,
                replace_all=edit.replace_all,
            )

        # All edits valid; write to disk
        try:
            await asyncio.to_thread(write_text, file_path, staged)
        except Exception as e:  # pragma: no cover
            return model.ToolResultItem(status="error", output=f"<tool_use_error>{e}</tool_use_error>")

        # Prepare UI extra: unified diff
        diff_lines = list(
            difflib.unified_diff(
                before.splitlines(),
                staged.splitlines(),
                fromfile=file_path,
                tofile=file_path,
                n=3,
            )
        )
        diff_text = "\n".join(diff_lines)
        ui_extra = model.DiffTextUIExtra(diff_text=diff_text)

        # Update tracker
        if file_tracker is not None:
            with contextlib.suppress(Exception):
                file_tracker[file_path] = Path(file_path).stat().st_mtime

        # Build output message
        lines = [f"Applied {len(args.edits)} edits to {file_path}:"]
        for i, edit in enumerate(args.edits, start=1):
            lines.append(f'{i}. Replaced "{edit.old_string}" with "{edit.new_string}"')
        return model.ToolResultItem(status="success", output="\n".join(lines), ui_extra=ui_extra)
