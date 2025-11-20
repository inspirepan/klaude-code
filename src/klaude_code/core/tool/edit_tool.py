from __future__ import annotations

import asyncio
import difflib
import os
from pathlib import Path

from pydantic import BaseModel, Field

from klaude_code.core.tool.tool_abc import ToolABC
from klaude_code.core.tool.tool_context import current_session_var
from klaude_code.core.tool.tool_registry import register
from klaude_code.protocol.llm_parameter import ToolSchema
from klaude_code.protocol.model import ToolResultItem
from klaude_code.protocol.tools import EDIT


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


@register(EDIT)
class EditTool(ToolABC):
    class EditArguments(BaseModel):
        file_path: str
        old_string: str
        new_string: str
        replace_all: bool = Field(default=False)

    @classmethod
    def schema(cls) -> ToolSchema:
        return ToolSchema(
            name=EDIT,
            type="function",
            description=(
                "Performs exact string replacements in files.\n\n"
                "Performs exact string replacements in files. \n\n"
                "Usage:\n"
                "- You must use your `Read` tool at least once in the conversation before editing. This tool will error if you attempt an edit without reading the file. \n"
                "- When editing text from Read tool output, ensure you preserve the exact indentation (tabs/spaces) as it appears AFTER the line number prefix. The line number prefix format is: spaces + line number + tab. Everything after that tab is the actual file content to match. Never include any part of the line number prefix in the old_string or new_string.\n"
                "- ALWAYS prefer editing existing files in the codebase. NEVER write new files unless explicitly required.\n"
                "- Only use emojis if the user explicitly requests it. Avoid adding emojis to files unless asked.\n"
                "- The edit will FAIL if `old_string` is not unique in the file. Either provide a larger string with more surrounding context to make it unique or use `replace_all` to change every instance of `old_string`. \n"
                "- Use `replace_all` for replacing and renaming strings across the file. This parameter is useful if you want to rename a variable for instance.\n"
                "- You can use this tool to create new files by providing an empty old_string.\n"
            ),
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

    # Validation utility for MultiEdit integration
    @classmethod
    def valid(
        cls, *, content: str, old_string: str, new_string: str, replace_all: bool
    ) -> str | None:  # returns error message or None
        if old_string == new_string:
            return (
                "<tool_use_error>No changes to make: old_string and new_string are exactly the same.</tool_use_error>"
            )
        if old_string == "":
            # Creation is allowed at call-level; for in-memory validation just ok
            return None
        count = content.count(old_string)
        if count == 0:
            return f"<tool_use_error>String to replace not found in file.\nString: {old_string}</tool_use_error>"
        if not replace_all and count > 1:
            return (
                f"<tool_use_error>Found {count} matches of the string to replace, but replace_all is false. To replace all occurrences, set replace_all to true. To replace only one occurrence, please provide more context to uniquely identify the instance.\n"
                f"String: {old_string}</tool_use_error>"
            )
        return None

    # Execute utility for MultiEdit integration
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
    async def call(cls, arguments: str) -> ToolResultItem:
        try:
            args = EditTool.EditArguments.model_validate_json(arguments)
        except Exception as e:  # pragma: no cover - defensive
            return ToolResultItem(status="error", output=f"Invalid arguments: {e}")

        file_path = os.path.abspath(args.file_path)

        # Common file errors
        if _is_directory(file_path):
            return ToolResultItem(
                status="error",
                output="<tool_use_error>Illegal operation on a directory. edit</tool_use_error>",
            )

        # FileTracker checks (only for editing existing files; creation handled separately)
        session = current_session_var.get()
        if args.old_string != "":
            if not _file_exists(file_path):
                # We require reading before editing
                return ToolResultItem(
                    status="error",
                    output=("File has not been read yet. Read it first before writing to it."),
                )
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

        # Creation cases
        if args.old_string == "":
            if _file_exists(file_path):
                # Check if the existing file is empty, if so, allow overwriting
                try:
                    existing_content = await asyncio.to_thread(_read_text, file_path)
                    if existing_content.strip() != "":
                        return ToolResultItem(
                            status="error",
                            output="<tool_use_error>Cannot create new file - file already exists.</tool_use_error>",
                        )
                except Exception:
                    return ToolResultItem(
                        status="error",
                        output="<tool_use_error>Cannot read existing file to check if it's empty.</tool_use_error>",
                    )
            # Create new file or overwrite empty file
            try:
                was_existing = _file_exists(file_path)
                await asyncio.to_thread(_write_text, file_path, args.new_string)
                # Update tracker
                if session is not None:
                    try:
                        session.file_tracker[file_path] = Path(file_path).stat().st_mtime
                    except Exception:
                        pass
                if was_existing:
                    return ToolResultItem(
                        status="success", output=f"Empty file overwritten successfully at: {file_path}"
                    )
                else:
                    return ToolResultItem(status="success", output=f"File created successfully at: {file_path}")
            except Exception as e:  # pragma: no cover
                return ToolResultItem(status="error", output=f"<tool_use_error>{e}</tool_use_error>")

        # Edit existing file: validate and apply
        try:
            before = await asyncio.to_thread(_read_text, file_path)
        except FileNotFoundError:
            return ToolResultItem(
                status="error",
                output="File has not been read yet. Read it first before writing to it.",
            )

        err = cls.valid(
            content=before, old_string=args.old_string, new_string=args.new_string, replace_all=args.replace_all
        )
        if err is not None:
            return ToolResultItem(status="error", output=err)

        after = cls.execute(
            content=before, old_string=args.old_string, new_string=args.new_string, replace_all=args.replace_all
        )

        # If nothing changed due to replacement semantics (should not happen after valid), guard anyway
        if before == after:
            return ToolResultItem(
                status="error",
                output=(
                    "<tool_use_error>No changes to make: old_string and new_string are exactly the same.</tool_use_error>"
                ),
            )

        # Write back
        try:
            await asyncio.to_thread(_write_text, file_path, after)
        except Exception as e:  # pragma: no cover
            return ToolResultItem(status="error", output=f"<tool_use_error>{e}</tool_use_error>")

        # Prepare UI extra: unified diff with 3 context lines
        diff_lines = list(
            difflib.unified_diff(
                before.splitlines(),
                after.splitlines(),
                fromfile=file_path,
                tofile=file_path,
                n=3,
            )
        )
        ui_extra = "\n".join(diff_lines)

        # Update tracker with new mtime
        if session is not None:
            try:
                session.file_tracker[file_path] = Path(file_path).stat().st_mtime
            except Exception:
                pass

        # Build output message
        if args.replace_all:
            msg = f"The file {file_path} has been updated. All occurrences of '{args.old_string}' were successfully replaced with '{args.new_string}'."
            return ToolResultItem(status="success", output=msg, ui_extra=ui_extra)

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
                    if "," in plus_range:
                        start = int(plus_range.split(",")[0])
                    else:
                        start = int(plus_range)
                    after_line_no = start - 1
                except Exception:
                    after_line_no = 0
                continue
            if line.startswith(" "):
                after_line_no += 1
                include_after_line_nos.append(after_line_no)
            elif line.startswith("+") and not line.startswith("+++ "):
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
        return ToolResultItem(status="success", output=output, ui_extra=ui_extra)
