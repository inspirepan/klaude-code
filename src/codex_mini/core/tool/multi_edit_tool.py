from __future__ import annotations

import difflib
import os
from pathlib import Path

from pydantic import BaseModel, Field

from codex_mini.core.tool.edit_tool import EditTool
from codex_mini.core.tool.tool_abc import ToolABC
from codex_mini.core.tool.tool_context import current_session_var
from codex_mini.core.tool.tool_registry import register
from codex_mini.protocol.llm_parameter import ToolSchema
from codex_mini.protocol.model import ToolResultItem

MULTI_EDIT_TOOL_NAME = "MultiEdit"


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


def _read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def _write_text(path: str, content: str) -> None:
    parent = Path(path).parent
    parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


@register(MULTI_EDIT_TOOL_NAME)
class MultiEditTool(ToolABC):
    class MultiEditEditItem(BaseModel):
        old_string: str
        new_string: str
        replace_all: bool = Field(default=False)

    class MultiEditArguments(BaseModel):
        file_path: str
        edits: list[MultiEditTool.MultiEditEditItem]

    @classmethod
    def schema(cls) -> ToolSchema:
        return ToolSchema(
            name=MULTI_EDIT_TOOL_NAME,
            type="function",
            description=(
                "This is a tool for making multiple edits to a single file in one operation. It is built on top of the Edit tool and allows you to perform multiple find-and-replace operations efficiently. Prefer this tool over the Edit tool when you need to make multiple edits to the same file.\n\n"
                "Before using this tool:\n\n"
                "1. Use the Read tool to understand the file's contents and context\n"
                "2. Verify the directory path is correct\n\n"
                "To make multiple file edits, provide the following:\n"
                "1. file_path: The absolute path to the file to modify (must be absolute, not relative)\n"
                "2. edits: An array of edit operations to perform, where each edit contains:\n"
                "   - old_string: The text to replace (must match the file contents exactly, including all whitespace and indentation)\n"
                "   - new_string: The edited text to replace the old_string\n"
                "   - replace_all: Replace all occurences of old_string. This parameter is optional and defaults to false.\n\n"
                "IMPORTANT:\n"
                "- All edits are applied in sequence, in the order they are provided\n"
                "- Each edit operates on the result of the previous edit\n"
                "- All edits must be valid for the operation to succeed - if any edit fails, none will be applied\n"
                "- This tool is ideal when you need to make several changes to different parts of the same file\n"
                "- For Jupyter notebooks (.ipynb files), use the NotebookEdit instead\n\n"
                "CRITICAL REQUIREMENTS:\n"
                "1. All edits follow the same requirements as the single Edit tool\n"
                "2. The edits are atomic - either all succeed or none are applied\n"
                "3. Plan your edits carefully to avoid conflicts between sequential operations\n\n"
                "WARNING:\n"
                "- The tool will fail if edits.old_string doesn't match the file contents exactly (including whitespace)\n"
                "- The tool will fail if edits.old_string and edits.new_string are the same\n"
                "- Since edits are applied in sequence, ensure that earlier edits don't affect the text that later edits are trying to find\n\n"
                "When making edits:\n"
                "- Ensure all edits result in idiomatic, correct code\n"
                "- Do not leave the code in a broken state\n"
                "- Always use absolute file paths (starting with /)\n"
                "- Only use emojis if the user explicitly requests it. Avoid adding emojis to files unless asked.\n"
                "- Use replace_all for replacing and renaming strings across the file. This parameter is useful if you want to rename a variable for instance.\n\n"
                "If you want to create a new file, use:\n"
                "- A new file path, including dir name if needed\n"
                "- First edit: empty old_string and the new file's contents as new_string\n"
                "- Subsequent edits: normal edit operations on the created content\n"
            ),
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
                "$schema": "http://json-schema.org/draft-07/schema#",
            },
        )

    @classmethod
    async def call(cls, arguments: str) -> ToolResultItem:
        try:
            args = MultiEditTool.MultiEditArguments.model_validate_json(arguments)
        except Exception as e:  # pragma: no cover - defensive
            return ToolResultItem(status="error", output=f"Invalid arguments: {e}")

        file_path = os.path.abspath(args.file_path)

        # Directory error first
        if _is_directory(file_path):
            return ToolResultItem(
                status="error",
                output="<tool_use_error>Illegal operation on a directory. multi_edit</tool_use_error>",
            )

        session = current_session_var.get()

        # FileTracker check:
        if _file_exists(file_path):
            if session is not None:
                tracked = session.file_tracker.get(file_path)
                if tracked is None:
                    return ToolResultItem(
                        status="error",
                        output=("File has not been read yet. Read it first before writing to it."),
                    )
                try:
                    current_mtime = Path(file_path).stat().st_mtime
                except Exception:
                    current_mtime = tracked
                if current_mtime != tracked:
                    return ToolResultItem(
                        status="error",
                        output=(
                            "File has been modified externally. Either by user or a linter. Read it first before writing to it."
                        ),
                    )
        else:
            # Allow creation only if first edit is creating content (old_string == "")
            if not args.edits or args.edits[0].old_string != "":
                return ToolResultItem(
                    status="error",
                    output=("File has not been read yet. Read it first before writing to it."),
                )

        # Load initial content (empty for new file case)
        if _file_exists(file_path):
            before = _read_text(file_path)
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
                return ToolResultItem(status="error", output=err)
            # Apply to staged content
            staged = EditTool.execute(
                content=staged,
                old_string=edit.old_string,
                new_string=edit.new_string,
                replace_all=edit.replace_all,
            )

        # All edits valid; write to disk
        try:
            _write_text(file_path, staged)
        except Exception as e:  # pragma: no cover
            return ToolResultItem(status="error", output=f"<tool_use_error>{e}</tool_use_error>")

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
        ui_extra = "\n".join(diff_lines)

        # Update tracker
        if session is not None:
            try:
                session.file_tracker[file_path] = Path(file_path).stat().st_mtime
            except Exception:
                pass

        # Build output message
        lines = [f"Applied {len(args.edits)} edits to {file_path}:"]
        for i, edit in enumerate(args.edits, start=1):
            lines.append(f'{i}. Replaced "{edit.old_string}" with "{edit.new_string}"')
        return ToolResultItem(status="success", output="\n".join(lines), ui_extra=ui_extra)
