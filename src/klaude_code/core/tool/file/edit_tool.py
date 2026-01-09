from __future__ import annotations

import asyncio
import contextlib
import difflib
import os
from pathlib import Path

from pydantic import BaseModel, Field

from klaude_code.const import DIFF_DEFAULT_CONTEXT_LINES
from klaude_code.core.tool.context import ToolContext
from klaude_code.core.tool.file._utils import file_exists, hash_text_sha256, is_directory, read_text, write_text
from klaude_code.core.tool.file.diff_builder import build_structured_diff
from klaude_code.core.tool.tool_abc import ToolABC, load_desc
from klaude_code.core.tool.tool_registry import register
from klaude_code.protocol import llm_param, message, model, tools


@register(tools.EDIT)
class EditTool(ToolABC):
    class EditArguments(BaseModel):
        file_path: str
        old_string: str
        new_string: str
        replace_all: bool = Field(default=False)

    @classmethod
    def schema(cls) -> llm_param.ToolSchema:
        return llm_param.ToolSchema(
            name=tools.EDIT,
            type="function",
            description=load_desc(Path(__file__).parent / "edit_tool.md"),
            parameters={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "The absolute path to the file to modify",
                    },
                    "old_string": {
                        "type": "string",
                        "description": "The text to replace",
                    },
                    "new_string": {
                        "type": "string",
                        "description": "The text to replace it with (must be different from old_string)",
                    },
                    "replace_all": {
                        "type": "boolean",
                        "default": False,
                        "description": "Replace all occurences of old_string (default false)",
                    },
                },
                "required": ["file_path", "old_string", "new_string"],
                "additionalProperties": False,
            },
        )

    @classmethod
    def valid(
        cls, *, content: str, old_string: str, new_string: str, replace_all: bool
    ) -> str | None:  # returns error message or None
        if old_string == new_string:
            return (
                "<tool_use_error>No changes to make: old_string and new_string are exactly the same.</tool_use_error>"
            )
        count = content.count(old_string)
        if count == 0:
            return f"<tool_use_error>String to replace not found in file.\nString: {old_string}</tool_use_error>"
        if not replace_all and count > 1:
            return (
                f"<tool_use_error>Found {count} matches of the string to replace, but replace_all is false. To replace all occurrences, set replace_all to true. To replace only one occurrence, please provide more context to uniquely identify the instance.\n"
                f"String: {old_string}</tool_use_error>"
            )
        return None

    @classmethod
    def execute(cls, *, content: str, old_string: str, new_string: str, replace_all: bool) -> str:
        if old_string == "":
            # Creating new file content
            return new_string
        if replace_all:
            return content.replace(old_string, new_string)
        # Replace one occurrence only (we already ensured uniqueness)
        return content.replace(old_string, new_string, 1)

    @classmethod
    async def call(cls, arguments: str, context: ToolContext) -> message.ToolResultMessage:
        try:
            args = EditTool.EditArguments.model_validate_json(arguments)
        except ValueError as e:  # pragma: no cover - defensive
            return message.ToolResultMessage(status="error", output_text=f"Invalid arguments: {e}")

        file_path = os.path.abspath(args.file_path)

        # Common file errors
        if is_directory(file_path):
            return message.ToolResultMessage(
                status="error",
                output_text="<tool_use_error>Illegal operation on a directory: edit</tool_use_error>",
            )

        if args.old_string == "":
            return message.ToolResultMessage(
                status="error",
                output_text=(
                    "<tool_use_error>old_string must not be empty for Edit. "
                    "To create or overwrite a file, use the Write tool instead.</tool_use_error>"
                ),
            )

        # FileTracker checks (only for editing existing files)
        file_tracker = context.file_tracker
        tracked_status: model.FileStatus | None = None
        if not file_exists(file_path):
            return message.ToolResultMessage(
                status="error",
                output_text=("File does not exist. If you want to create a file, use the Write tool instead."),
            )
        tracked_status = file_tracker.get(file_path)
        if tracked_status is None:
            return message.ToolResultMessage(
                status="error",
                output_text=("File has not been read yet. Read it first before writing to it."),
            )

        # Edit existing file: validate and apply
        try:
            before = await asyncio.to_thread(read_text, file_path)
        except FileNotFoundError:
            return message.ToolResultMessage(
                status="error",
                output_text="File has not been read yet. Read it first before writing to it.",
            )

        # Re-check external modifications using content hash when available.
        if tracked_status.content_sha256 is not None:
            current_sha256 = hash_text_sha256(before)
            if current_sha256 != tracked_status.content_sha256:
                return message.ToolResultMessage(
                    status="error",
                    output_text=(
                        "File has been modified externally. Either by user or a linter. Read it first before writing to it."
                    ),
                )
        else:
            # Backward-compat: old sessions only stored mtime.
            try:
                current_mtime = Path(file_path).stat().st_mtime
            except OSError:
                current_mtime = tracked_status.mtime
            if current_mtime != tracked_status.mtime:
                return message.ToolResultMessage(
                    status="error",
                    output_text=(
                        "File has been modified externally. Either by user or a linter. Read it first before writing to it."
                    ),
                )

        err = cls.valid(
            content=before,
            old_string=args.old_string,
            new_string=args.new_string,
            replace_all=args.replace_all,
        )
        if err is not None:
            return message.ToolResultMessage(status="error", output_text=err)

        after = cls.execute(
            content=before,
            old_string=args.old_string,
            new_string=args.new_string,
            replace_all=args.replace_all,
        )

        # If nothing changed due to replacement semantics (should not happen after valid), guard anyway
        if before == after:
            return message.ToolResultMessage(
                status="error",
                output_text=(
                    "<tool_use_error>No changes to make: old_string and new_string are exactly the same.</tool_use_error>"
                ),
            )

        # Write back
        try:
            await asyncio.to_thread(write_text, file_path, after)
        except (OSError, UnicodeError) as e:  # pragma: no cover
            return message.ToolResultMessage(status="error", output_text=f"<tool_use_error>{e}</tool_use_error>")

        # Prepare UI extra: unified diff with default context lines
        diff_lines = list(
            difflib.unified_diff(
                before.splitlines(),
                after.splitlines(),
                fromfile=file_path,
                tofile=file_path,
                n=DIFF_DEFAULT_CONTEXT_LINES,
            )
        )
        ui_extra = build_structured_diff(before, after, file_path=file_path)

        # Update tracker with new mtime and content hash
        with contextlib.suppress(Exception):
            existing = file_tracker.get(file_path)
            is_mem = existing.is_memory if existing else False
            file_tracker[file_path] = model.FileStatus(
                mtime=Path(file_path).stat().st_mtime,
                content_sha256=hash_text_sha256(after),
                is_memory=is_mem,
            )

        # Build output message
        if args.replace_all:
            msg = f"The file {file_path} has been updated. All occurrences of '{args.old_string}' were successfully replaced with '{args.new_string}'."
            return message.ToolResultMessage(status="success", output_text=msg, ui_extra=ui_extra)

        # For single replacement, show a snippet consisting of context + added lines only
        # Parse the diff to collect target line numbers in the 'after' file
        include_after_line_nos: list[int] = []
        after_line_no = 0
        for line in diff_lines:
            if line.startswith("@@"):
                # Parse header: @@ -l,s +l,s @@
                # Extract the +l,s part
                try:
                    header = line
                    plus = header.split("+", 1)[1]
                    plus_range = plus.split(" ")[0]
                    start = int(plus_range.split(",")[0]) if "," in plus_range else int(plus_range)
                    after_line_no = start - 1
                except (ValueError, IndexError):
                    after_line_no = 0
                continue
            if line.startswith(" ") or (line.startswith("+") and not line.startswith("+++ ")):
                after_line_no += 1
                include_after_line_nos.append(after_line_no)
            elif line.startswith("-") and not line.startswith("--- "):
                # Removed line does not advance after_line_no
                continue
            else:
                # file header lines etc.
                continue

        # Build numbered snippet from the new content
        snippet_lines: list[str] = []
        after_lines = after.splitlines()
        for no in include_after_line_nos:
            if 1 <= no <= len(after_lines):
                snippet_lines.append(f"{no:>6}→{after_lines[no - 1]}")

        snippet = "\n".join(snippet_lines)
        output = (
            f"The file {file_path} has been updated. Here's the result of running `cat -n` on a snippet of the edited file:\n"
            f"{snippet}"
        )
        return message.ToolResultMessage(status="success", output_text=output, ui_extra=ui_extra)
