import asyncio
import difflib
import os
import re
from pathlib import Path

from pydantic import BaseModel

from codex_mini.core.tool import apply_patch as apply_patch_tool
from codex_mini.core.tool.tool_context import current_session_var
from codex_mini.protocol.model import ToolResultItem


class MaybeParseApplyPatchCommandResult(BaseModel):
    is_apply_patch: bool
    patch_text: str | None = None


class ApplyPatchHandler:
    APPLY_PATCH_COMMANDS = ["apply_patch", "applypatch"]

    @staticmethod
    def _extract_heredoc_from_bash(script: str) -> tuple[str, str | None] | None:
        """Extract heredoc body and optional cd path from bash script.

        Returns:
            (heredoc_body, cd_path) if successful, None if no match
        """
        # Pattern for: cd <path> && apply_patch <<'EOF' ... EOF
        cd_pattern = r"^cd\s+([^\s]+)\s+&&\s+(apply_patch|applypatch)\s+<<'([^']+)'\s*\n(.*)\n\3$"
        match = re.search(cd_pattern, script, re.DOTALL | re.MULTILINE)
        if match:
            cd_path = match.group(1)
            heredoc_body = match.group(4)
            return (heredoc_body, cd_path)

        # Pattern for: apply_patch <<'EOF' ... EOF
        direct_pattern = r"^(apply_patch|applypatch)\s+<<'([^']+)'\s*\n(.*)\n\2$"
        match = re.search(direct_pattern, script, re.DOTALL | re.MULTILINE)
        if match:
            heredoc_body = match.group(3)
            return (heredoc_body, None)

        return None

    @staticmethod
    def _extract_heredoc_from_string(content: str) -> str | None:
        """Extract heredoc content from a string like '<<EOF\ncontent\nEOF'.

        Returns:
            heredoc_body if successful, None if no match
        """
        # Pattern for: <<'EOF' ... EOF or <<EOF ... EOF
        pattern = r"^<<'?([^'\s]+)'?\s*\n(.*)\n\1$"
        match = re.search(pattern, content, re.DOTALL | re.MULTILINE)
        if match:
            return match.group(2)
        return None

    @staticmethod
    def _extract_apply_patch_from_bash(script: str) -> str | None:
        """Extract apply_patch content from bash script (non-heredoc).

        Returns:
            patch_text if successful, None if no match
        """
        # Pattern for: apply_patch 'content' or apply_patch "content"
        quoted_pattern = r"^(apply_patch|applypatch)\s+['\"](.+)['\"]$"
        match = re.search(quoted_pattern, script, re.DOTALL)
        if match:
            return match.group(2)

        # Pattern for: apply_patch content (without quotes)
        unquoted_pattern = r"^(apply_patch|applypatch)\s+(.+)$"
        match = re.search(unquoted_pattern, script, re.DOTALL)
        if match:
            content = match.group(2).strip()
            # Make sure it's not a heredoc
            if not content.startswith("<<"):
                return content

        return None

    @staticmethod
    def maybe_parse_apply_patch_command(argv: list[str]) -> MaybeParseApplyPatchCommandResult:
        """Parse argv to determine if it's an apply_patch command."""
        # Case 1: Direct invocation: apply_patch <patch> or applypatch <patch>
        if len(argv) >= 2:
            cmd, body = argv[0], argv[1]
            if cmd in ApplyPatchHandler.APPLY_PATCH_COMMANDS:
                # Case 2: apply_patch heredoc (direct, not via bash)
                heredoc_content = ApplyPatchHandler._extract_heredoc_from_string(body)
                if heredoc_content is not None:
                    return MaybeParseApplyPatchCommandResult(is_apply_patch=True, patch_text=heredoc_content)
                # Case 1: apply_patch direct content
                return MaybeParseApplyPatchCommandResult(is_apply_patch=True, patch_text=body)

        # Cases 3 & 4: bash -lc wrapped commands
        if len(argv) == 3 and argv[0] == "bash" and argv[1] == "-lc":
            script = argv[2]

            # Case 4: bash -lc "apply_patch heredoc"
            heredoc_result = ApplyPatchHandler._extract_heredoc_from_bash(script)
            if heredoc_result is not None:
                heredoc_body, _cd_path = heredoc_result  # cd_path not used in current implementation
                return MaybeParseApplyPatchCommandResult(is_apply_patch=True, patch_text=heredoc_body)

            # Case 3: bash -lc "apply_patch direct"
            patch_content = ApplyPatchHandler._extract_apply_patch_from_bash(script)
            if patch_content is not None:
                return MaybeParseApplyPatchCommandResult(is_apply_patch=True, patch_text=patch_content)

        # Not an apply_patch command
        return MaybeParseApplyPatchCommandResult(is_apply_patch=False)

    @classmethod
    async def handle_apply_patch(cls, patch_text: str) -> ToolResultItem:
        try:
            output, diff_text = await asyncio.to_thread(cls._apply_patch_in_thread, patch_text)
        except apply_patch_tool.DiffError as e:
            return ToolResultItem(
                status="error",
                output=str(e),
            )
        except Exception as e:
            return ToolResultItem(
                status="error",
                output=f"Execution error: {e}",
            )
        return ToolResultItem(
            status="success",
            output=output,
            ui_extra=diff_text,
        )

    @staticmethod
    def _apply_patch_in_thread(patch_text: str) -> tuple[str, str]:
        ap = apply_patch_tool
        normalized_start = patch_text.lstrip()
        if not normalized_start.startswith("*** Begin Patch"):
            raise ap.DiffError("apply_patch content must start with *** Begin Patch")

        workspace_root = os.path.realpath(os.getcwd())
        session = current_session_var.get()

        def resolve_path(path: str) -> str:
            if os.path.isabs(path):
                raise ap.DiffError(f"Absolute path not allowed: {path}")
            candidate = os.path.realpath(os.path.join(workspace_root, path))
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
                with open(resolved, "r", encoding="utf-8") as f:
                    orig[path] = f.read()
            except OSError as e:
                raise ap.DiffError(f"Failed to read {path}: {e}") from e

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
            with open(resolved, "w", encoding="utf-8") as f:
                f.write(content)

            # Update file tracker
            if session is not None:
                try:
                    session.file_tracker[resolved] = Path(resolved).stat().st_mtime
                except Exception:
                    pass

        def remove_fn(path: str) -> None:
            resolved = resolve_path(path)
            if not os.path.exists(resolved):
                raise ap.DiffError(f"Missing File: {path}")
            if os.path.isdir(resolved):
                raise ap.DiffError(f"Cannot delete directory: {path}")
            os.remove(resolved)

            # Remove from file tracker
            if session is not None:
                try:
                    session.file_tracker.pop(resolved, None)
                except Exception:
                    pass

        ap.apply_commit(commit, write_fn, remove_fn)
        return "Done!", diff_text

    @staticmethod
    def _commit_to_diff(commit: apply_patch_tool.Commit) -> str:
        diff_chunks: list[str] = []
        for path, change in commit.changes.items():
            chunk = ApplyPatchHandler._render_change_diff(path, change)
            if chunk:
                if diff_chunks:
                    diff_chunks.append("")
                diff_chunks.extend(chunk)
        return "\n".join(diff_chunks)

    @staticmethod
    def _render_change_diff(path: str, change: apply_patch_tool.FileChange) -> list[str]:
        lines: list[str] = []
        if change.type == apply_patch_tool.ActionType.ADD:
            lines.append(f"diff --git a/{path} b/{path}")
            lines.append("new file mode 100644")
            new_lines = ApplyPatchHandler._split_lines(change.new_content)
            lines.extend(ApplyPatchHandler._unified_diff([], new_lines, fromfile="/dev/null", tofile=f"b/{path}"))
            return lines
        if change.type == apply_patch_tool.ActionType.DELETE:
            lines.append(f"diff --git a/{path} b/{path}")
            lines.append("deleted file mode 100644")
            old_lines = ApplyPatchHandler._split_lines(change.old_content)
            lines.extend(ApplyPatchHandler._unified_diff(old_lines, [], fromfile=f"a/{path}", tofile="/dev/null"))
            return lines
        if change.type == apply_patch_tool.ActionType.UPDATE:
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
