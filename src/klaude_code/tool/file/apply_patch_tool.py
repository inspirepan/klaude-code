
"""ApplyPatch tool providing direct patch application capability."""

import asyncio
import contextlib
import os
from pathlib import Path

from pydantic import BaseModel

from klaude_code.protocol import llm_param, message, tools
from klaude_code.protocol.models import (
    DiffFileDiff,
    DiffUIExtra,
    FileChangeSummary,
    FileStatus,
    MarkdownDocUIExtra,
    MultiUIExtra,
    MultiUIExtraItem,
    ToolResultUIExtra,
    ToolStatus,
)
from klaude_code.tool.core.abc import ToolABC, load_desc
from klaude_code.tool.core.context import FileTracker, ToolContext
from klaude_code.tool.core.registry import register
from klaude_code.tool.file import apply_patch as apply_patch_module
from klaude_code.tool.file._utils import hash_text_sha256
from klaude_code.tool.file.diff_builder import build_structured_file_diff, build_unified_diff_text


class ApplyPatchHandler:
    @classmethod
    async def handle_apply_patch(cls, patch_text: str, context: ToolContext) -> message.ToolResultMessage:
        try:
            status, output, ui_extra = await asyncio.to_thread(
                cls._apply_patch_in_thread,
                patch_text,
                context.file_tracker,
                context.file_change_summary,
                context.work_dir,
            )
        except apply_patch_module.DiffError as error:
            return message.ToolResultMessage(status="error", output_text=str(error))
        except Exception as error:  # pragma: no cover  # unexpected errors bubbled to tool result
            return message.ToolResultMessage(status="error", output_text=f"Execution error: {error}")
        return message.ToolResultMessage(
            status=status,
            output_text=output,
            ui_extra=ui_extra,
        )

    @staticmethod
    def _apply_patch_in_thread(
        patch_text: str,
        file_tracker: FileTracker,
        file_change_summary: FileChangeSummary | None,
        work_dir: Path,
    ) -> tuple[ToolStatus, str, ToolResultUIExtra | None]:
        ap = apply_patch_module
        normalized_start = patch_text.lstrip()
        if not normalized_start.startswith("*** Begin Patch"):
            raise ap.DiffError("apply_patch content must start with *** Begin Patch")

        workspace_root = os.path.realpath(str(work_dir))

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

        def open_fn(path: str) -> str:
            resolved = resolve_path(path)
            if not os.path.exists(resolved):
                raise ap.DiffError(f"Missing File: {path}")
            if os.path.isdir(resolved):
                raise ap.DiffError(f"Cannot apply patch to directory: {path}")
            try:
                with open(resolved, encoding="utf-8") as handle:
                    return handle.read()
            except OSError as error:
                raise ap.DiffError(f"Failed to read {path}: {error}") from error

        patch_result = ap.build_patch_result(patch_text, open_fn)
        commits = list(ap.iter_commits(patch_result))
        landed_changes = list(ap.iter_successful_changes(patch_result))
        output_text = ap.format_patch_result(patch_result)
        if not commits:
            raise ap.DiffError(output_text)

        diff_ui = ApplyPatchHandler._changes_to_structured_diff(landed_changes)

        if file_change_summary is not None:
            for change_path, change in landed_changes:
                resolved = resolve_path(change_path)
                if change.type == apply_patch_module.ActionType.ADD:
                    file_change_summary.record_created(resolved)
                elif change.type == apply_patch_module.ActionType.UPDATE:
                    tracked_path = change.move_path if change.move_path else change_path
                    resolved = resolve_path(tracked_path)
                    file_change_summary.record_edited(resolved)
                file_diff = build_structured_file_diff(
                    change.old_content or "", change.new_content or "", file_path=change_path
                )
                file_change_summary.add_diff(added=file_diff.stats_add, removed=file_diff.stats_remove, path=resolved)

        md_items: list[MarkdownDocUIExtra] = []
        for change_path, change in landed_changes:
            if change.type == apply_patch_module.ActionType.ADD and change_path.endswith(".md"):
                md_items.append(
                    MarkdownDocUIExtra(
                        file_path=resolve_path(change_path),
                        content=change.new_content or "",
                    )
                )

        def write_fn(path: str, content: str) -> None:
            resolved = resolve_path(path)
            if os.path.isdir(resolved):
                raise ap.DiffError(f"Cannot overwrite directory: {path}")
            parent = os.path.dirname(resolved)
            if parent:
                os.makedirs(parent, exist_ok=True)
            with open(resolved, "w", encoding="utf-8") as handle:
                handle.write(content)

            with contextlib.suppress(Exception):  # pragma: no cover - file tracker best-effort
                existing = file_tracker.get(resolved)
                is_mem = existing.is_memory if existing else False
                is_skill = existing.is_skill if existing else False
                is_dir = existing.is_directory if existing else False
                file_tracker[resolved] = FileStatus(
                    mtime=Path(resolved).stat().st_mtime,
                    content_sha256=hash_text_sha256(content),
                    cached_content=content,
                    is_memory=is_mem,
                    is_skill=is_skill,
                    skill_attachment_source=None,
                    is_directory=is_dir,
                )

        def remove_fn(path: str) -> None:
            resolved = resolve_path(path)
            if not os.path.exists(resolved):
                raise ap.DiffError(f"Missing File: {path}")
            if os.path.isdir(resolved):
                raise ap.DiffError(f"Cannot delete directory: {path}")
            os.remove(resolved)

            with contextlib.suppress(Exception):  # pragma: no cover - file tracker best-effort
                file_tracker.pop(resolved, None)

        for commit in commits:
            ap.apply_commit(commit, write_fn, remove_fn)

        # apply_patch can include multiple operations. If we added markdown files,
        # return a MultiUIExtra so UI can render markdown previews (without showing a diff for those markdown adds).
        if md_items:
            items: list[MultiUIExtraItem] = []
            items.extend(md_items)
            if diff_ui.files:
                items.append(diff_ui)
            return "success", output_text, MultiUIExtra(items=items)

        return "success", output_text, diff_ui if diff_ui.files else None

    @staticmethod
    def _changes_to_structured_diff(
        changes: list[tuple[str, apply_patch_module.FileChange]],
    ) -> DiffUIExtra:
        files: list[DiffFileDiff] = []
        raw_chunks: list[str] = []
        for path, change in changes:
            if change.type == apply_patch_module.ActionType.ADD:
                # For markdown files created via Add File, we render content via MarkdownDocUIExtra instead of a diff.
                if path.endswith(".md"):
                    continue
                files.append(build_structured_file_diff("", change.new_content or "", file_path=path))
                raw = build_unified_diff_text("", change.new_content or "", from_file="/dev/null", to_file=path)
                if raw:
                    raw_chunks.append(raw)
            elif change.type == apply_patch_module.ActionType.DELETE:
                files.append(build_structured_file_diff(change.old_content or "", "", file_path=path))
                raw = build_unified_diff_text(change.old_content or "", "", from_file=path, to_file="/dev/null")
                if raw:
                    raw_chunks.append(raw)
            elif change.type == apply_patch_module.ActionType.UPDATE:
                display_path = path
                to_path = path
                if change.move_path and change.move_path != path:
                    display_path = f"{path} → {change.move_path}"
                    to_path = change.move_path
                files.append(
                    build_structured_file_diff(
                        change.old_content or "", change.new_content or "", file_path=display_path
                    )
                )
                raw = build_unified_diff_text(
                    change.old_content or "", change.new_content or "", from_file=path, to_file=to_path
                )
                if raw:
                    raw_chunks.append(raw)

        raw_unified_diff = "\n".join(raw_chunks) if raw_chunks else ""
        return DiffUIExtra(files=files, raw_unified_diff=raw_unified_diff)

@register(tools.APPLY_PATCH)
class ApplyPatchTool(ToolABC):
    class ApplyPatchArguments(BaseModel):
        patch: str

    @classmethod
    def schema(cls) -> llm_param.ToolSchema:
        return llm_param.ToolSchema(
            name=tools.APPLY_PATCH,
            type="function",
            description=load_desc(Path(__file__).parent / "apply_patch_tool.md"),
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
    async def call(cls, arguments: str, context: ToolContext) -> message.ToolResultMessage:
        try:
            args = cls.ApplyPatchArguments.model_validate_json(arguments)
        except ValueError as exc:
            return message.ToolResultMessage(status="error", output_text=f"Invalid arguments: {exc}")
        return await cls.call_with_args(args, context)

    @classmethod
    async def call_with_args(cls, args: ApplyPatchArguments, context: ToolContext) -> message.ToolResultMessage:
        return await ApplyPatchHandler.handle_apply_patch(args.patch, context)
