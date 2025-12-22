"""ApplyPatch tool providing direct patch application capability."""

import asyncio
import contextlib
import os
from pathlib import Path

from pydantic import BaseModel

from klaude_code.core.tool.file import apply_patch as apply_patch_module
from klaude_code.core.tool.file._utils import hash_text_sha256
from klaude_code.core.tool.file.diff_builder import build_structured_file_diff
from klaude_code.core.tool.tool_abc import ToolABC, load_desc
from klaude_code.core.tool.tool_context import get_current_file_tracker
from klaude_code.core.tool.tool_registry import register
from klaude_code.protocol import llm_param, model, tools


class ApplyPatchHandler:
    @classmethod
    async def handle_apply_patch(cls, patch_text: str) -> model.ToolResultItem:
        try:
            output, ui_extra = await asyncio.to_thread(cls._apply_patch_in_thread, patch_text)
        except apply_patch_module.DiffError as error:
            return model.ToolResultItem(status="error", output=str(error))
        except Exception as error:  # pragma: no cover  # unexpected errors bubbled to tool result
            return model.ToolResultItem(status="error", output=f"Execution error: {error}")
        return model.ToolResultItem(
            status="success",
            output=output,
            ui_extra=ui_extra,
        )

    @staticmethod
    def _apply_patch_in_thread(patch_text: str) -> tuple[str, model.ToolResultUIExtra]:
        ap = apply_patch_module
        normalized_start = patch_text.lstrip()
        if not normalized_start.startswith("*** Begin Patch"):
            raise ap.DiffError("apply_patch content must start with *** Begin Patch")

        workspace_root = os.path.realpath(os.getcwd())
        file_tracker = get_current_file_tracker()

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
                with open(resolved, encoding="utf-8") as handle:
                    orig[path] = handle.read()
            except OSError as error:
                raise ap.DiffError(f"Failed to read {path}: {error}") from error

        patch, _ = ap.text_to_patch(patch_text, orig)
        commit = ap.patch_to_commit(patch, orig)
        diff_ui = ApplyPatchHandler._commit_to_structured_diff(commit)

        md_items: list[model.MarkdownDocUIExtra] = []
        for change_path, change in commit.changes.items():
            if change.type == apply_patch_module.ActionType.ADD and change_path.endswith(".md"):
                md_items.append(
                    model.MarkdownDocUIExtra(
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

            if file_tracker is not None:
                with contextlib.suppress(Exception):  # pragma: no cover - file tracker best-effort
                    existing = file_tracker.get(resolved)
                    is_mem = existing.is_memory if existing else False
                    file_tracker[resolved] = model.FileStatus(
                        mtime=Path(resolved).stat().st_mtime,
                        content_sha256=hash_text_sha256(content),
                        is_memory=is_mem,
                    )

        def remove_fn(path: str) -> None:
            resolved = resolve_path(path)
            if not os.path.exists(resolved):
                raise ap.DiffError(f"Missing File: {path}")
            if os.path.isdir(resolved):
                raise ap.DiffError(f"Cannot delete directory: {path}")
            os.remove(resolved)

            if file_tracker is not None:
                with contextlib.suppress(Exception):  # pragma: no cover - file tracker best-effort
                    file_tracker.pop(resolved, None)

        ap.apply_commit(commit, write_fn, remove_fn)

        # apply_patch can include multiple operations. If we added markdown files,
        # return a MultiUIExtra so UI can render markdown previews (without showing a diff for those markdown adds).
        if md_items:
            items: list[model.MultiUIExtraItem] = []
            items.extend(md_items)
            if diff_ui.files:
                items.append(diff_ui)
            return "Done!", model.MultiUIExtra(items=items)

        return "Done!", diff_ui

    @staticmethod
    def _commit_to_structured_diff(commit: apply_patch_module.Commit) -> model.DiffUIExtra:
        files: list[model.DiffFileDiff] = []
        for path in sorted(commit.changes):
            change = commit.changes[path]
            if change.type == apply_patch_module.ActionType.ADD:
                # For markdown files created via Add File, we render content via MarkdownDocUIExtra instead of a diff.
                if path.endswith(".md"):
                    continue
                files.append(build_structured_file_diff("", change.new_content or "", file_path=path))
            elif change.type == apply_patch_module.ActionType.DELETE:
                files.append(build_structured_file_diff(change.old_content or "", "", file_path=path))
            elif change.type == apply_patch_module.ActionType.UPDATE:
                display_path = path
                if change.move_path and change.move_path != path:
                    display_path = f"{path} → {change.move_path}"
                files.append(
                    build_structured_file_diff(
                        change.old_content or "", change.new_content or "", file_path=display_path
                    )
                )
        return model.DiffUIExtra(files=files)


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
    async def call(cls, arguments: str) -> model.ToolResultItem:
        try:
            args = cls.ApplyPatchArguments.model_validate_json(arguments)
        except ValueError as exc:
            return model.ToolResultItem(status="error", output=f"Invalid arguments: {exc}")
        return await cls.call_with_args(args)

    @classmethod
    async def call_with_args(cls, args: ApplyPatchArguments) -> model.ToolResultItem:
        return await ApplyPatchHandler.handle_apply_patch(args.patch)
