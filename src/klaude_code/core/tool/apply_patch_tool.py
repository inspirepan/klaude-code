"""ApplyPatch tool providing direct patch application capability."""

import asyncio
import difflib
import os
from pathlib import Path

from pydantic import BaseModel

from klaude_code.core.tool import apply_patch as apply_patch_module
from klaude_code.core.tool.tool_abc import ToolABC
from klaude_code.core.tool.tool_context import current_session_var
from klaude_code.core.tool.tool_registry import register
from klaude_code.protocol import tools
from klaude_code.protocol.llm_parameter import ToolSchema
from klaude_code.protocol.model import (ToolResultItem, ToolResultUIExtra,
                                        ToolResultUIExtraType)


class ApplyPatchHandler:
    @classmethod
    async def handle_apply_patch(cls, patch_text: str) -> ToolResultItem:
        try:
            output, diff_text = await asyncio.to_thread(cls._apply_patch_in_thread, patch_text)
        except apply_patch_module.DiffError as error:
            return ToolResultItem(status="error", output=str(error))
        except Exception as error:  # pragma: no cover  # unexpected errors bubbled to tool result
            return ToolResultItem(status="error", output=f"Execution error: {error}")
        return ToolResultItem(
            status="success",
            output=output,
            ui_extra=ToolResultUIExtra(type=ToolResultUIExtraType.DIFF_TEXT, diff_text=diff_text),
        )

    @staticmethod
    def _apply_patch_in_thread(patch_text: str) -> tuple[str, str]:
        ap = apply_patch_module
        normalized_start = patch_text.lstrip()
        if not normalized_start.startswith("*** Begin Patch"):
            raise ap.DiffError("apply_patch content must start with *** Begin Patch")

        workspace_root = os.path.realpath(os.getcwd())
        session = current_session_var.get()

        def resolve_path(path: str) -> str:
            candidate = os.path.realpath(path if os.path.isabs(path) else os.path.join(workspace_root, path))
            if not os.path.isabs(path):
                try:
                    common = os.path.commonpath([workspace_root, candidate])
                except ValueError:
                    raise ap.DiffError(f"Path escapes workspace: {path}") from None
                if common != workspace_root:
                    raise ap.DiffError(f"Path escapes workspace: {path}")
            return candidate

        orig: dict[str, str] = {}
        for path in ap.identify_files_needed(patch_text):
            resolved = resolve_path(path)
            if not os.path.exists(resolved):
                raise ap.DiffError(f"Missing File: {path}")
            if os.path.isdir(resolved):
                raise ap.DiffError(f"Cannot apply patch to directory: {path}")
            try:
                with open(resolved, "r", encoding="utf-8") as handle:
                    orig[path] = handle.read()
            except OSError as error:
                raise ap.DiffError(f"Failed to read {path}: {error}") from error

        patch, _ = ap.text_to_patch(patch_text, orig)
        commit = ap.patch_to_commit(patch, orig)
        diff_text = ApplyPatchHandler._commit_to_diff(commit)

        def write_fn(path: str, content: str) -> None:
            resolved = resolve_path(path)
            if os.path.isdir(resolved):
                raise ap.DiffError(f"Cannot overwrite directory: {path}")
            parent = os.path.dirname(resolved)
            if parent:
                os.makedirs(parent, exist_ok=True)
            with open(resolved, "w", encoding="utf-8") as handle:
                handle.write(content)

            if session is not None:
                try:
                    session.file_tracker[resolved] = Path(resolved).stat().st_mtime
                except Exception:  # pragma: no cover - file tracker best-effort
                    pass

        def remove_fn(path: str) -> None:
            resolved = resolve_path(path)
            if not os.path.exists(resolved):
                raise ap.DiffError(f"Missing File: {path}")
            if os.path.isdir(resolved):
                raise ap.DiffError(f"Cannot delete directory: {path}")
            os.remove(resolved)

            if session is not None:
                try:
                    session.file_tracker.pop(resolved, None)
                except Exception:  # pragma: no cover - file tracker best-effort
                    pass

        ap.apply_commit(commit, write_fn, remove_fn)
        return "Done!", diff_text

    @staticmethod
    def _commit_to_diff(commit: apply_patch_module.Commit) -> str:
        diff_chunks: list[str] = []
        for path, change in commit.changes.items():
            chunk = ApplyPatchHandler._render_change_diff(path, change)
            if chunk:
                if diff_chunks:
                    diff_chunks.append("")
                diff_chunks.extend(chunk)
        return "\n".join(diff_chunks)

    @staticmethod
    def _render_change_diff(path: str, change: apply_patch_module.FileChange) -> list[str]:
        lines: list[str] = []
        if change.type == apply_patch_module.ActionType.ADD:
            lines.append(f"diff --git a/{path} b/{path}")
            lines.append("new file mode 100644")
            new_lines = ApplyPatchHandler._split_lines(change.new_content)
            lines.extend(ApplyPatchHandler._unified_diff([], new_lines, fromfile="/dev/null", tofile=f"b/{path}"))
            return lines
        if change.type == apply_patch_module.ActionType.DELETE:
            lines.append(f"diff --git a/{path} b/{path}")
            lines.append("deleted file mode 100644")
            old_lines = ApplyPatchHandler._split_lines(change.old_content)
            lines.extend(ApplyPatchHandler._unified_diff(old_lines, [], fromfile=f"a/{path}", tofile="/dev/null"))
            return lines
        if change.type == apply_patch_module.ActionType.UPDATE:
            new_path = change.move_path or path
            lines.append(f"diff --git a/{path} b/{new_path}")
            if change.move_path and change.move_path != path:
                lines.append(f"rename from {path}")
                lines.append(f"rename to {new_path}")
            old_lines = ApplyPatchHandler._split_lines(change.old_content)
            new_lines = ApplyPatchHandler._split_lines(change.new_content)
            lines.extend(
                ApplyPatchHandler._unified_diff(old_lines, new_lines, fromfile=f"a/{path}", tofile=f"b/{new_path}")
            )
            return lines
        return lines

    @staticmethod
    def _unified_diff(
        old_lines: list[str],
        new_lines: list[str],
        *,
        fromfile: str,
        tofile: str,
    ) -> list[str]:
        diff_lines = list(
            difflib.unified_diff(
                old_lines,
                new_lines,
                fromfile=fromfile,
                tofile=tofile,
                lineterm="",
            )
        )
        if not diff_lines:
            diff_lines = [f"--- {fromfile}", f"+++ {tofile}"]
        return diff_lines

    @staticmethod
    def _split_lines(text: str | None) -> list[str]:
        if not text:
            return []
        return text.splitlines()


@register(tools.APPLY_PATCH)
class ApplyPatchTool(ToolABC):
    class ApplyPatchArguments(BaseModel):
        patch: str

    @classmethod
    def schema(cls) -> ToolSchema:
        return ToolSchema(
            name=tools.APPLY_PATCH,
            type="function",
            description="""Apply a unified diff patch to a file within the workspace.""",
            parameters={
                "type": "object",
                "properties": {
                    "patch": {
                        "type": "string",
                        "description": """Patch content""",
                    },
                },
                "required": ["patch"],
            },
        )

    @classmethod
    async def call(cls, arguments: str) -> ToolResultItem:
        try:
            args = cls.ApplyPatchArguments.model_validate_json(arguments)
        except ValueError as exc:
            return ToolResultItem(status="error", output=f"Invalid arguments: {exc}")
        return await cls.call_with_args(args)

    @classmethod
    async def call_with_args(cls, args: ApplyPatchArguments) -> ToolResultItem:
        return await ApplyPatchHandler.handle_apply_patch(args.patch)
