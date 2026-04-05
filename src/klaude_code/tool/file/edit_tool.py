from __future__ import annotations

import asyncio
import contextlib
import os
from pathlib import Path

from pydantic import BaseModel, Field

from klaude_code.const import EDIT_MAX_FILE_SIZE
from klaude_code.protocol import llm_param, message, model, tools
from klaude_code.tool.context import ToolContext
from klaude_code.tool.file._utils import (
    file_exists,
    find_actual_string,
    hash_text_sha256,
    is_directory,
    preserve_quote_style,
    read_text_with_encoding,
    strip_trailing_whitespace,
    write_text,
)
from klaude_code.tool.file.diff_builder import build_structured_diff
from klaude_code.tool.tool_abc import ToolABC, load_desc
from klaude_code.tool.tool_registry import register


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

        # Smart deletion: when deleting a single occurrence (new_string is empty, not replace_all)
        # and old_string doesn't end with a newline, also remove the trailing newline to avoid
        # leaving blank lines. Only for single replacement to avoid miscount with replace_all.
        if not replace_all and new_string == "" and "\n" not in old_string and content.find(old_string + "\n") != -1:
            return content.replace(old_string + "\n", new_string, 1)

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
        if not file_exists(file_path):
            return message.ToolResultMessage(
                status="error",
                output_text=("File does not exist. If you want to create a file, use the Write tool instead."),
            )

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
                output_text=f"<tool_use_error>File is too large to edit ({size_mb:.0f}MB). Maximum editable file size is {limit_mb:.0f}MB.</tool_use_error>",
            )

        tracked_status = file_tracker.get(file_path)
        if tracked_status is None:
            return message.ToolResultMessage(
                status="error",
                output_text=("File has not been read yet. Read it first before writing to it."),
            )

        # Edit existing file: validate and apply
        try:
            before, file_encoding = await asyncio.to_thread(read_text_with_encoding, file_path)
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

        # Quote normalization: find actual string in file (handles curly quotes)
        actual_old_string = find_actual_string(before, args.old_string)
        if actual_old_string is None:
            actual_old_string = args.old_string  # fall through to valid() which will report not-found

        # Strip trailing whitespace from new_string (except for markdown files)
        is_markdown = file_path.lower().endswith((".md", ".mdx"))
        new_string = args.new_string if is_markdown else strip_trailing_whitespace(args.new_string)

        # Preserve curly quote style when old_string was matched via normalization
        new_string = preserve_quote_style(args.old_string, actual_old_string, new_string)

        err = cls.valid(
            content=before,
            old_string=actual_old_string,
            new_string=new_string,
            replace_all=args.replace_all,
        )
        if err is not None:
            return message.ToolResultMessage(status="error", output_text=err)

        after = cls.execute(
            content=before,
            old_string=actual_old_string,
            new_string=new_string,
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

        # Write back (preserve original encoding)
        try:
            await asyncio.to_thread(write_text, file_path, after, file_encoding)
        except (OSError, UnicodeError) as e:  # pragma: no cover
            return message.ToolResultMessage(status="error", output_text=f"<tool_use_error>{e}</tool_use_error>")

        ui_extra = build_structured_diff(before, after, file_path=file_path)
        if context.file_change_summary is not None:
            context.file_change_summary.record_edited(file_path)
            context.file_change_summary.add_diff(
                added=ui_extra.files[0].stats_add,
                removed=ui_extra.files[0].stats_remove,
                path=file_path,
            )

        # Update tracker with new mtime and content hash
        with contextlib.suppress(Exception):
            existing = file_tracker.get(file_path)
            is_mem = existing.is_memory if existing else False
            is_skill = existing.is_skill if existing else False
            is_dir = existing.is_directory if existing else False
            file_tracker[file_path] = model.FileStatus(
                mtime=Path(file_path).stat().st_mtime,
                content_sha256=hash_text_sha256(after),
                cached_content=after,
                is_memory=is_mem,
                is_skill=is_skill,
                skill_attachment_source=None,
                is_directory=is_dir,
            )

        # Build output message
        if args.replace_all:
            msg = f"The file {file_path} has been updated. All occurrences were successfully replaced."
        else:
            msg = f"The file {file_path} has been updated successfully."
        return message.ToolResultMessage(status="success", output_text=msg, ui_extra=ui_extra)
