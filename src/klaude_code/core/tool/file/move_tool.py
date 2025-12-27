from __future__ import annotations

import asyncio
import contextlib
import os
from pathlib import Path

from pydantic import BaseModel, Field

from klaude_code.core.tool.file._utils import file_exists, hash_text_sha256, is_directory, read_text, write_text
from klaude_code.core.tool.file.diff_builder import build_structured_diff
from klaude_code.core.tool.tool_abc import ToolABC, load_desc
from klaude_code.core.tool.tool_context import get_current_file_tracker
from klaude_code.core.tool.tool_registry import register
from klaude_code.protocol import llm_param, model, tools


class MoveArguments(BaseModel):
    source_file_path: str
    start_line: int = Field(ge=1, description="Start line number (1-indexed, inclusive)")
    end_line: int = Field(ge=1, description="End line number (1-indexed, inclusive)")
    target_file_path: str
    insert_line: int = Field(ge=1, description="Line number to insert before (1-indexed)")


def _build_context_snippet(
    all_lines: list[str],
    start_line: int,
    end_line: int,
    context_lines: int = 3,
    marker: str = "cut here",
) -> str:
    """Build a snippet showing context around a cut/insert point.

    Args:
        all_lines: All lines of the file (after modification).
        start_line: 1-indexed start line of the context focus area.
        end_line: 1-indexed end line of the context focus area.
        context_lines: Number of context lines before and after.
        marker: Text to show in the separator line.

    Returns:
        Formatted snippet with context and separator.
    """
    result: list[str] = []

    # Context before
    ctx_start = max(1, start_line - context_lines)
    for line_no in range(ctx_start, start_line):
        idx = line_no - 1
        if idx < len(all_lines):
            content = all_lines[idx].rstrip("\n")
            result.append(f"{line_no:>6}\t{content}")

    # Separator
    result.append(f"  -------- {marker} --------")

    # Context after
    ctx_end = min(len(all_lines), end_line + context_lines)
    for line_no in range(end_line, ctx_end + 1):
        idx = line_no - 1
        if idx < len(all_lines):
            content = all_lines[idx].rstrip("\n")
            result.append(f"{line_no:>6}\t{content}")

    return "\n".join(result)


def _build_insert_context_snippet(
    all_lines: list[str],
    insert_line: int,
    inserted_count: int,
    context_lines: int = 3,
) -> str:
    """Build a snippet showing context around inserted content.

    Args:
        all_lines: All lines of the file (after insertion).
        insert_line: 1-indexed line where content was inserted.
        inserted_count: Number of lines that were inserted.
        context_lines: Number of context lines before and after.

    Returns:
        Formatted snippet with context and inserted content highlighted.
    """
    result: list[str] = []
    insert_end = insert_line + inserted_count - 1

    # Context before
    ctx_start = max(1, insert_line - context_lines)
    for line_no in range(ctx_start, insert_line):
        idx = line_no - 1
        if idx < len(all_lines):
            content = all_lines[idx].rstrip("\n")
            result.append(f"{line_no:>6}\t{content}")

    # Start separator
    result.append("  -------- inserted --------")

    # Inserted content
    for line_no in range(insert_line, insert_end + 1):
        idx = line_no - 1
        if idx < len(all_lines):
            content = all_lines[idx].rstrip("\n")
            result.append(f"{line_no:>6}\t{content}")

    # End separator
    result.append("  -------- end --------")

    # Context after
    ctx_end = min(len(all_lines), insert_end + context_lines)
    for line_no in range(insert_end + 1, ctx_end + 1):
        idx = line_no - 1
        if idx < len(all_lines):
            content = all_lines[idx].rstrip("\n")
            result.append(f"{line_no:>6}\t{content}")

    return "\n".join(result)


@register(tools.MOVE)
class MoveTool(ToolABC):
    @classmethod
    def schema(cls) -> llm_param.ToolSchema:
        return llm_param.ToolSchema(
            name=tools.MOVE,
            type="function",
            description=load_desc(Path(__file__).parent / "move_tool.md"),
            parameters={
                "type": "object",
                "properties": {
                    "source_file_path": {
                        "type": "string",
                        "description": "The absolute path to the source file to cut from",
                    },
                    "start_line": {
                        "type": "integer",
                        "description": "Start line number (1-indexed, inclusive)",
                    },
                    "end_line": {
                        "type": "integer",
                        "description": "End line number (1-indexed, inclusive)",
                    },
                    "target_file_path": {
                        "type": "string",
                        "description": "The absolute path to the target file to paste into",
                    },
                    "insert_line": {
                        "type": "integer",
                        "description": "Line number to insert before (1-indexed)",
                    },
                },
                "required": ["source_file_path", "start_line", "end_line", "target_file_path", "insert_line"],
                "additionalProperties": False,
            },
        )

    @classmethod
    async def call(cls, arguments: str) -> model.ToolResultItem:
        try:
            args = MoveArguments.model_validate_json(arguments)
        except ValueError as e:
            return model.ToolResultItem(status="error", output=f"Invalid arguments: {e}")

        source_path = os.path.abspath(args.source_file_path)
        target_path = os.path.abspath(args.target_file_path)
        same_file = source_path == target_path

        # Validate paths
        if is_directory(source_path):
            return model.ToolResultItem(
                status="error",
                output="<tool_use_error>Source path is a directory, not a file.</tool_use_error>",
            )
        if is_directory(target_path):
            return model.ToolResultItem(
                status="error",
                output="<tool_use_error>Target path is a directory, not a file.</tool_use_error>",
            )

        # Validate line range
        if args.start_line > args.end_line:
            return model.ToolResultItem(
                status="error",
                output="<tool_use_error>start_line must be <= end_line.</tool_use_error>",
            )

        # Check file tracker
        file_tracker = get_current_file_tracker()
        source_exists = file_exists(source_path)
        target_exists = file_exists(target_path)

        if not source_exists:
            return model.ToolResultItem(
                status="error",
                output="<tool_use_error>Source file does not exist.</tool_use_error>",
            )

        source_status: model.FileStatus | None = None
        target_status: model.FileStatus | None = None

        if file_tracker is not None:
            source_status = file_tracker.get(source_path)
            if source_status is None:
                return model.ToolResultItem(
                    status="error",
                    output="Source file has not been read yet. Read it first.",
                )
            if target_exists:
                target_status = file_tracker.get(target_path)
                if target_status is None:
                    return model.ToolResultItem(
                        status="error",
                        output="Target file has not been read yet. Read it first before writing to it.",
                    )

        # Read source file
        try:
            source_content = await asyncio.to_thread(read_text, source_path)
        except OSError as e:
            return model.ToolResultItem(
                status="error", output=f"<tool_use_error>Failed to read source: {e}</tool_use_error>"
            )

        # Verify source hasn't been modified externally
        if source_status is not None and source_status.content_sha256 is not None:
            current_sha256 = hash_text_sha256(source_content)
            if current_sha256 != source_status.content_sha256:
                return model.ToolResultItem(
                    status="error",
                    output="Source file has been modified externally. Read it first before editing.",
                )

        source_lines = source_content.splitlines(keepends=True)

        # Validate line numbers against actual file
        if args.start_line > len(source_lines):
            return model.ToolResultItem(
                status="error",
                output=f"<tool_use_error>start_line {args.start_line} exceeds file length {len(source_lines)}.</tool_use_error>",
            )
        if args.end_line > len(source_lines):
            return model.ToolResultItem(
                status="error",
                output=f"<tool_use_error>end_line {args.end_line} exceeds file length {len(source_lines)}.</tool_use_error>",
            )

        # Extract the lines to move (convert to 0-indexed)
        cut_lines = source_lines[args.start_line - 1 : args.end_line]

        # Read target file content (if exists)
        target_before = ""
        if target_exists:
            try:
                target_before = await asyncio.to_thread(read_text, target_path)
            except OSError as e:
                return model.ToolResultItem(
                    status="error", output=f"<tool_use_error>Failed to read target: {e}</tool_use_error>"
                )

            # Verify target hasn't been modified externally
            if target_status is not None and target_status.content_sha256 is not None:
                current_sha256 = hash_text_sha256(target_before)
                if current_sha256 != target_status.content_sha256:
                    return model.ToolResultItem(
                        status="error",
                        output="Target file has been modified externally. Read it first before writing to it.",
                    )

        # For new target file, only allow insert_line = 1
        if not target_exists and args.insert_line != 1:
            return model.ToolResultItem(
                status="error",
                output="<tool_use_error>Target file does not exist. Use insert_line=1 to create new file.</tool_use_error>",
            )

        # Build new content for both files
        source_before = source_content

        if same_file:
            # Same file move: more complex logic
            # First remove the cut lines, then insert at adjusted position
            new_lines = source_lines[: args.start_line - 1] + source_lines[args.end_line :]

            # Adjust insert position if it was after the cut region
            adjusted_insert = args.insert_line
            if args.insert_line > args.end_line:
                adjusted_insert -= args.end_line - args.start_line + 1
            elif args.insert_line > args.start_line:
                # Insert position is within the cut region - error
                return model.ToolResultItem(
                    status="error",
                    output="<tool_use_error>insert_line cannot be within the cut range for same-file move.</tool_use_error>",
                )

            # Validate adjusted insert line
            if adjusted_insert > len(new_lines) + 1:
                return model.ToolResultItem(
                    status="error",
                    output=f"<tool_use_error>insert_line {args.insert_line} is out of bounds after cut.</tool_use_error>",
                )

            # Insert at adjusted position
            final_lines = new_lines[: adjusted_insert - 1] + cut_lines + new_lines[adjusted_insert - 1 :]
            source_after = "".join(final_lines)
            target_after = source_after  # Same file

            # Write the file once
            try:
                await asyncio.to_thread(write_text, source_path, source_after)
            except OSError as e:
                return model.ToolResultItem(
                    status="error", output=f"<tool_use_error>Failed to write: {e}</tool_use_error>"
                )

            # Update tracker
            if file_tracker is not None:
                with contextlib.suppress(Exception):
                    existing = file_tracker.get(source_path)
                    is_mem = existing.is_memory if existing else False
                    file_tracker[source_path] = model.FileStatus(
                        mtime=Path(source_path).stat().st_mtime,
                        content_sha256=hash_text_sha256(source_after),
                        is_memory=is_mem,
                    )

            ui_extra = build_structured_diff(source_before, source_after, file_path=source_path)
            cut_count = args.end_line - args.start_line + 1

            # Build context snippets for same-file move
            final_lines = source_after.splitlines(keepends=True)
            # Show context around cut location (now joined)
            cut_context = _build_context_snippet(final_lines, args.start_line, args.start_line, marker="cut here")
            # Show context around insert location
            insert_context = _build_insert_context_snippet(final_lines, adjusted_insert, cut_count)

            output = (
                f"Moved {cut_count} lines within {source_path} "
                f"(from lines {args.start_line}-{args.end_line} to line {args.insert_line}).\n\n"
                f"Source context (after cut):\n{cut_context}\n\n"
                f"Insert context:\n{insert_context}"
            )
            return model.ToolResultItem(
                status="success",
                output=output,
                ui_extra=ui_extra,
            )
        else:
            # Different files
            # Remove lines from source
            new_source_lines = source_lines[: args.start_line - 1] + source_lines[args.end_line :]
            source_after = "".join(new_source_lines)

            # Insert into target
            target_lines = target_before.splitlines(keepends=True) if target_before else []

            # Validate insert_line for existing target
            if target_exists and args.insert_line > len(target_lines) + 1:
                return model.ToolResultItem(
                    status="error",
                    output=f"<tool_use_error>insert_line {args.insert_line} exceeds target file length + 1.</tool_use_error>",
                )

            new_target_lines = target_lines[: args.insert_line - 1] + cut_lines + target_lines[args.insert_line - 1 :]
            target_after = "".join(new_target_lines)

            # Ensure target ends with newline if source content did
            if cut_lines and not target_after.endswith("\n"):
                target_after += "\n"

            # Write both files
            try:
                await asyncio.to_thread(write_text, source_path, source_after)
                await asyncio.to_thread(write_text, target_path, target_after)
            except OSError as e:
                return model.ToolResultItem(
                    status="error", output=f"<tool_use_error>Failed to write: {e}</tool_use_error>"
                )

            # Update tracker for both files
            if file_tracker is not None:
                with contextlib.suppress(Exception):
                    existing = file_tracker.get(source_path)
                    is_mem = existing.is_memory if existing else False
                    file_tracker[source_path] = model.FileStatus(
                        mtime=Path(source_path).stat().st_mtime,
                        content_sha256=hash_text_sha256(source_after),
                        is_memory=is_mem,
                    )
                with contextlib.suppress(Exception):
                    existing = file_tracker.get(target_path)
                    is_mem = existing.is_memory if existing else False
                    file_tracker[target_path] = model.FileStatus(
                        mtime=Path(target_path).stat().st_mtime,
                        content_sha256=hash_text_sha256(target_after),
                        is_memory=is_mem,
                    )

            # Build UI extra with diffs for both files
            source_diff = build_structured_diff(source_before, source_after, file_path=source_path)
            target_diff = build_structured_diff(target_before, target_after, file_path=target_path)

            ui_extra: model.ToolResultUIExtra | None = None
            if source_diff and target_diff:
                ui_extra = model.MultiUIExtra(items=[source_diff, target_diff])
            elif source_diff:
                ui_extra = source_diff
            elif target_diff:
                ui_extra = target_diff

            cut_count = args.end_line - args.start_line + 1
            action = "created" if not target_exists else "updated"

            # Build context snippets for different-file move
            source_after_lines = source_after.splitlines(keepends=True)
            target_after_lines = target_after.splitlines(keepends=True)

            # Show context around cut location in source file
            source_context = _build_context_snippet(
                source_after_lines, args.start_line, args.start_line, marker="cut here"
            )
            # Show context around insert location in target file
            target_context = _build_insert_context_snippet(target_after_lines, args.insert_line, cut_count)

            output = (
                f"Moved {cut_count} lines from {source_path} (lines {args.start_line}-{args.end_line}) "
                f"to {target_path} ({action}) at line {args.insert_line}.\n\n"
                f"Source file context (after move):\n{source_context}\n\n"
                f"Target file context (after insert):\n{target_context}"
            )
            return model.ToolResultItem(
                status="success",
                output=output,
                ui_extra=ui_extra,
            )
