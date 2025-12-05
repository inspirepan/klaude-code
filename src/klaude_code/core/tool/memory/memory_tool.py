from __future__ import annotations

import asyncio
import difflib
import os
import shutil
import subprocess
import urllib.parse
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from klaude_code.core.tool.tool_abc import ToolABC, load_desc
from klaude_code.core.tool.tool_registry import register
from klaude_code.protocol import llm_param, model, tools

MEMORY_VIRTUAL_ROOT = "/memories"
MEMORY_DIR_NAME = ".claude/memories"


def _get_git_root() -> Path | None:
    """Get the git repository root directory."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return Path(result.stdout.strip())
    except Exception:
        pass
    return None


def _get_memories_root() -> Path:
    """Get the actual memories directory path."""
    git_root = _get_git_root()
    if git_root is not None:
        return git_root / MEMORY_DIR_NAME
    return Path.cwd() / MEMORY_DIR_NAME


def _ensure_memories_dir() -> Path:
    """Ensure the memories directory exists and return its path."""
    memories_root = _get_memories_root()
    memories_root.mkdir(parents=True, exist_ok=True)
    return memories_root


def _validate_path(virtual_path: str) -> tuple[Path | None, str | None]:
    """
    Validate a virtual path and return the actual filesystem path.

    Returns:
        (actual_path, None) on success
        (None, error_message) on failure
    """
    # Check for URL-encoded traversal attempts
    decoded = urllib.parse.unquote(virtual_path)
    if ".." in decoded or ".." in virtual_path:
        return None, "Path traversal is not allowed"

    # Must start with /memories
    if not virtual_path.startswith(MEMORY_VIRTUAL_ROOT):
        return None, f"Path must start with {MEMORY_VIRTUAL_ROOT}"

    # Get relative path from /memories
    relative = "" if virtual_path == MEMORY_VIRTUAL_ROOT else virtual_path[len(MEMORY_VIRTUAL_ROOT) :].lstrip("/")

    memories_root = _get_memories_root()
    actual_path = memories_root / relative if relative else memories_root

    # Resolve to canonical path and verify it's still within memories
    try:
        resolved = actual_path.resolve()
        memories_resolved = memories_root.resolve()
        # Check if resolved path is within or equal to memories root
        try:
            resolved.relative_to(memories_resolved)
        except ValueError:
            # Also allow the exact memories root
            if resolved != memories_resolved:
                return None, "Path traversal is not allowed"
    except Exception as e:
        return None, f"Invalid path: {e}"

    return actual_path, None


def _format_numbered_line(line_no: int, content: str) -> str:
    return f"{line_no:>6}|{content}"


def _make_diff_ui_extra(before: str, after: str, path: str) -> model.DiffTextUIExtra:
    diff_lines = list(
        difflib.unified_diff(
            before.splitlines(),
            after.splitlines(),
            fromfile=path,
            tofile=path,
            n=3,
        )
    )
    diff_text = "\n".join(diff_lines)
    return model.DiffTextUIExtra(diff_text=diff_text)


@register(tools.MEMORY)
class MemoryTool(ToolABC):
    class MemoryArguments(BaseModel):
        command: Literal["view", "create", "str_replace", "insert", "delete", "rename"]
        path: str | None = Field(default=None)
        # view command
        view_range: list[int] | None = Field(default=None)
        # create command
        file_text: str | None = Field(default=None)
        # str_replace command
        old_str: str | None = Field(default=None)
        new_str: str | None = Field(default=None)
        # insert command
        insert_line: int | None = Field(default=None)
        insert_text: str | None = Field(default=None)
        # rename command
        old_path: str | None = Field(default=None)
        new_path: str | None = Field(default=None)

    @classmethod
    def schema(cls) -> llm_param.ToolSchema:
        return llm_param.ToolSchema(
            name=tools.MEMORY,
            type="function",
            description=load_desc(Path(__file__).parent / "memory_tool.md"),
            parameters={
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "enum": [
                            "view",
                            "create",
                            "str_replace",
                            "insert",
                            "delete",
                            "rename",
                        ],
                        "description": "The memory operation to perform",
                    },
                    "path": {
                        "type": "string",
                        "description": "Path starting with /memories (for view, create, str_replace, insert, delete)",
                    },
                    "view_range": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "Optional [start, end] line range for view command (1-indexed)",
                    },
                    "file_text": {
                        "type": "string",
                        "description": "Content to write (for create command)",
                    },
                    "old_str": {
                        "type": "string",
                        "description": "Text to find (for str_replace command)",
                    },
                    "new_str": {
                        "type": "string",
                        "description": "Text to replace with (for str_replace command)",
                    },
                    "insert_line": {
                        "type": "integer",
                        "description": "Line number to insert at (for insert command, 1-indexed)",
                    },
                    "insert_text": {
                        "type": "string",
                        "description": "Text to insert (for insert command)",
                    },
                    "old_path": {
                        "type": "string",
                        "description": "Source path (for rename command)",
                    },
                    "new_path": {
                        "type": "string",
                        "description": "Destination path (for rename command)",
                    },
                },
                "required": ["command"],
                "additionalProperties": False,
            },
        )

    @classmethod
    async def call(cls, arguments: str) -> model.ToolResultItem:
        try:
            args = cls.MemoryArguments.model_validate_json(arguments)
        except Exception as e:
            return model.ToolResultItem(status="error", output=f"Invalid arguments: {e}")

        command = args.command
        if command == "view":
            return await cls._view(args)
        elif command == "create":
            return await cls._create(args)
        elif command == "str_replace":
            return await cls._str_replace(args)
        elif command == "insert":
            return await cls._insert(args)
        elif command == "delete":
            return await cls._delete(args)
        elif command == "rename":
            return await cls._rename(args)
        else:
            return model.ToolResultItem(status="error", output=f"Unknown command: {command}")

    @classmethod
    async def _view(cls, args: MemoryArguments) -> model.ToolResultItem:
        if args.path is None:
            return model.ToolResultItem(status="error", output="path is required for view command")

        actual_path, error = _validate_path(args.path)
        if error:
            return model.ToolResultItem(status="error", output=error)
        assert actual_path is not None

        # Ensure memories directory exists
        _ensure_memories_dir()

        if not actual_path.exists():
            return model.ToolResultItem(status="error", output=f"Path does not exist: {args.path}")

        if actual_path.is_dir():
            # List directory contents
            try:
                entries = sorted(
                    actual_path.iterdir(),
                    key=lambda p: (not p.is_dir(), p.name.lower()),
                )
                lines = [f"Directory: {args.path}"]
                for entry in entries:
                    prefix = "/" if entry.is_dir() else ""
                    lines.append(f"- {entry.name}{prefix}")
                if len(entries) == 0:
                    lines.append("(empty directory)")
                return model.ToolResultItem(status="success", output="\n".join(lines))
            except Exception as e:
                return model.ToolResultItem(status="error", output=f"Failed to list directory: {e}")
        else:
            # Read file contents
            try:
                content = await asyncio.to_thread(actual_path.read_text, encoding="utf-8")
                lines = content.splitlines()
                total_lines = len(lines)

                # Apply view_range if specified
                start = 1
                end = total_lines
                if args.view_range and len(args.view_range) >= 2:
                    start = max(1, args.view_range[0])
                    end = min(total_lines, args.view_range[1])

                if start > total_lines:
                    return model.ToolResultItem(
                        status="success",
                        output=f"File has {total_lines} lines, requested start line {start} is beyond end of file",
                    )

                selected = lines[start - 1 : end]
                numbered = [_format_numbered_line(start + i, line) for i, line in enumerate(selected)]
                output = "\n".join(numbered)
                if not output:
                    output = "(empty file)"
                return model.ToolResultItem(status="success", output=output)
            except Exception as e:
                return model.ToolResultItem(status="error", output=f"Failed to read file: {e}")

    @classmethod
    async def _create(cls, args: MemoryArguments) -> model.ToolResultItem:
        if args.path is None:
            return model.ToolResultItem(status="error", output="path is required for create command")
        if args.file_text is None:
            return model.ToolResultItem(status="error", output="file_text is required for create command")

        actual_path, error = _validate_path(args.path)
        if error:
            return model.ToolResultItem(status="error", output=error)
        assert actual_path is not None

        # Cannot create the root directory itself
        if args.path == MEMORY_VIRTUAL_ROOT or args.path == MEMORY_VIRTUAL_ROOT + "/":
            return model.ToolResultItem(
                status="error",
                output="Cannot create the memories root directory as a file",
            )

        try:
            # Read existing content for diff (if file exists)
            before = ""
            if actual_path.exists():
                before = await asyncio.to_thread(actual_path.read_text, encoding="utf-8")

            # Ensure parent directories exist
            actual_path.parent.mkdir(parents=True, exist_ok=True)
            await asyncio.to_thread(actual_path.write_text, args.file_text, encoding="utf-8")

            ui_extra = _make_diff_ui_extra(before, args.file_text, args.path)
            return model.ToolResultItem(status="success", output=f"File created: {args.path}", ui_extra=ui_extra)
        except Exception as e:
            return model.ToolResultItem(status="error", output=f"Failed to create file: {e}")

    @classmethod
    async def _str_replace(cls, args: MemoryArguments) -> model.ToolResultItem:
        if args.path is None:
            return model.ToolResultItem(status="error", output="path is required for str_replace command")
        if args.old_str is None:
            return model.ToolResultItem(status="error", output="old_str is required for str_replace command")
        if args.new_str is None:
            return model.ToolResultItem(status="error", output="new_str is required for str_replace command")

        actual_path, error = _validate_path(args.path)
        if error:
            return model.ToolResultItem(status="error", output=error)
        assert actual_path is not None

        if not actual_path.exists():
            return model.ToolResultItem(status="error", output=f"File does not exist: {args.path}")
        if actual_path.is_dir():
            return model.ToolResultItem(status="error", output="Cannot perform str_replace on a directory")

        try:
            before = await asyncio.to_thread(actual_path.read_text, encoding="utf-8")
            if args.old_str not in before:
                return model.ToolResultItem(status="error", output=f"String not found in file: {args.old_str}")

            after = before.replace(args.old_str, args.new_str, 1)
            await asyncio.to_thread(actual_path.write_text, after, encoding="utf-8")

            ui_extra = _make_diff_ui_extra(before, after, args.path)
            return model.ToolResultItem(
                status="success",
                output=f"Replaced text in {args.path}",
                ui_extra=ui_extra,
            )
        except Exception as e:
            return model.ToolResultItem(status="error", output=f"Failed to replace text: {e}")

    @classmethod
    async def _insert(cls, args: MemoryArguments) -> model.ToolResultItem:
        if args.path is None:
            return model.ToolResultItem(status="error", output="path is required for insert command")
        if args.insert_line is None:
            return model.ToolResultItem(status="error", output="insert_line is required for insert command")
        if args.insert_text is None:
            return model.ToolResultItem(status="error", output="insert_text is required for insert command")

        actual_path, error = _validate_path(args.path)
        if error:
            return model.ToolResultItem(status="error", output=error)
        assert actual_path is not None

        if not actual_path.exists():
            return model.ToolResultItem(status="error", output=f"File does not exist: {args.path}")
        if actual_path.is_dir():
            return model.ToolResultItem(status="error", output="Cannot insert into a directory")

        try:
            before = await asyncio.to_thread(actual_path.read_text, encoding="utf-8")
            lines = before.splitlines(keepends=True)

            # Handle empty file
            if not lines:
                lines = []

            # Normalize insert_line (1-indexed)
            insert_idx = max(0, args.insert_line - 1)
            insert_idx = min(insert_idx, len(lines))

            # Ensure insert_text ends with newline if inserting in middle
            insert_text = args.insert_text
            if insert_idx < len(lines) and not insert_text.endswith("\n"):
                insert_text += "\n"

            lines.insert(insert_idx, insert_text)
            after = "".join(lines)
            await asyncio.to_thread(actual_path.write_text, after, encoding="utf-8")

            ui_extra = _make_diff_ui_extra(before, after, args.path)
            return model.ToolResultItem(
                status="success",
                output=f"Inserted text at line {args.insert_line} in {args.path}",
                ui_extra=ui_extra,
            )
        except Exception as e:
            return model.ToolResultItem(status="error", output=f"Failed to insert text: {e}")

    @classmethod
    async def _delete(cls, args: MemoryArguments) -> model.ToolResultItem:
        if args.path is None:
            return model.ToolResultItem(status="error", output="path is required for delete command")

        # Prevent deleting the root memories directory
        if args.path == MEMORY_VIRTUAL_ROOT or args.path == MEMORY_VIRTUAL_ROOT + "/":
            return model.ToolResultItem(status="error", output="Cannot delete the memories root directory")

        actual_path, error = _validate_path(args.path)
        if error:
            return model.ToolResultItem(status="error", output=error)
        assert actual_path is not None

        if not actual_path.exists():
            return model.ToolResultItem(status="error", output=f"Path does not exist: {args.path}")

        try:
            if actual_path.is_dir():
                await asyncio.to_thread(shutil.rmtree, actual_path)
                return model.ToolResultItem(status="success", output=f"Directory deleted: {args.path}")
            else:
                await asyncio.to_thread(os.remove, actual_path)
                return model.ToolResultItem(status="success", output=f"File deleted: {args.path}")
        except Exception as e:
            return model.ToolResultItem(status="error", output=f"Failed to delete: {e}")

    @classmethod
    async def _rename(cls, args: MemoryArguments) -> model.ToolResultItem:
        if args.old_path is None:
            return model.ToolResultItem(status="error", output="old_path is required for rename command")
        if args.new_path is None:
            return model.ToolResultItem(status="error", output="new_path is required for rename command")

        # Prevent renaming the root memories directory
        if args.old_path == MEMORY_VIRTUAL_ROOT or args.old_path == MEMORY_VIRTUAL_ROOT + "/":
            return model.ToolResultItem(status="error", output="Cannot rename the memories root directory")

        old_actual, error = _validate_path(args.old_path)
        if error:
            return model.ToolResultItem(status="error", output=f"Invalid old_path: {error}")
        assert old_actual is not None

        new_actual, error = _validate_path(args.new_path)
        if error:
            return model.ToolResultItem(status="error", output=f"Invalid new_path: {error}")
        assert new_actual is not None

        if not old_actual.exists():
            return model.ToolResultItem(status="error", output=f"Source path does not exist: {args.old_path}")
        if new_actual.exists():
            return model.ToolResultItem(status="error", output=f"Destination already exists: {args.new_path}")

        try:
            # Ensure parent directory of destination exists
            new_actual.parent.mkdir(parents=True, exist_ok=True)
            await asyncio.to_thread(shutil.move, str(old_actual), str(new_actual))
            return model.ToolResultItem(status="success", output=f"Renamed {args.old_path} to {args.new_path}")
        except Exception as e:
            return model.ToolResultItem(status="error", output=f"Failed to rename: {e}")
