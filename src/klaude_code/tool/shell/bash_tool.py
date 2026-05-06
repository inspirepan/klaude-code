import asyncio
import contextlib
import os
import re
import shlex
import signal
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from pydantic import BaseModel

from klaude_code.const import BASH_DEFAULT_TIMEOUT_MS, BASH_TERMINATE_TIMEOUT_SEC
from klaude_code.protocol import llm_param, message, tools
from klaude_code.protocol.models import FileChangeSummary, FileDiffStats, FileStatus, TaskFileChange
from klaude_code.tool.core.abc import ToolABC, load_desc
from klaude_code.tool.core.context import ToolContext
from klaude_code.tool.core.registry import register
from klaude_code.tool.shell.command_safety import is_safe_command

# Regex to strip ANSI and terminal control sequences from command output
#
# This is intentionally broader than just SGR color codes (e.g. "\x1b[31m").
# Many interactive or TUI-style programs emit additional escape sequences
# that move the cursor, clear the screen, or switch screen buffers
# (CSI/OSC/DCS/APC/PM, etc). If these reach the Rich console, they can
# corrupt the REPL layout. We therefore remove all of them before
# rendering the output.
_ANSI_ESCAPE_RE = re.compile(
    r"""
    \x1B
    (?:
        \[[0-?]*[ -/]*[@-~]         |  # CSI sequences
        \][0-?]*.*?(?:\x07|\x1B\\) |  # OSC sequences
        P.*?(?:\x07|\x1B\\)       |  # DCS sequences
        _.*?(?:\x07|\x1B\\)       |  # APC sequences
        \^.*?(?:\x07|\x1B\\)      |  # PM sequences
        [@-Z\\-_]                      # 2-char sequences
    )
    """,
    re.VERBOSE | re.DOTALL,
)

_STREAM_POLL_INTERVAL_SEC = 0.05
_GIT_FILE_CHANGE_EXCLUDED_DIRS: Final = (".venv", "node_modules")


@dataclass
class _GitFileChangeBaseline:
    repo_root: Path
    pathspec: str
    object_dir: tempfile.TemporaryDirectory[str]
    alternate_object_dir: Path
    tree: str = ""


def _run_git(cwd: Path, args: list[str], *, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        errors="surrogateescape",
        check=True,
    )


def _run_git_bytes(
    cwd: Path, args: list[str], *, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        check=True,
    )


def _git_env(baseline: _GitFileChangeBaseline, *, index_file: str | None = None) -> dict[str, str]:
    env = os.environ.copy()
    if index_file is not None:
        env["GIT_INDEX_FILE"] = index_file
    env["GIT_OBJECT_DIRECTORY"] = baseline.object_dir.name
    alternates = [str(baseline.alternate_object_dir)]
    if existing := env.get("GIT_ALTERNATE_OBJECT_DIRECTORIES"):
        alternates.append(existing)
    env["GIT_ALTERNATE_OBJECT_DIRECTORIES"] = os.pathsep.join(alternates)
    return env


def _git_file_change_pathspecs(pathspec: str) -> list[str]:
    return [
        pathspec,
        *(f":(exclude,glob)**/{excluded_dir}/**" for excluded_dir in _GIT_FILE_CHANGE_EXCLUDED_DIRS),
    ]


def _snapshot_git_worktree_tree(baseline: _GitFileChangeBaseline) -> str:
    with tempfile.NamedTemporaryFile(prefix="klaude-git-index-") as index_file:
        env = _git_env(baseline, index_file=index_file.name)
        has_head = (
            subprocess.run(
                ["git", "rev-parse", "--verify", "HEAD"],
                cwd=baseline.repo_root,
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            ).returncode
            == 0
        )
        if has_head:
            _run_git(baseline.repo_root, ["read-tree", "HEAD"], env=env)
        else:
            _run_git(baseline.repo_root, ["read-tree", "--empty"], env=env)
        _run_git(baseline.repo_root, ["add", "-A", "--", *_git_file_change_pathspecs(baseline.pathspec)], env=env)
        return _run_git(baseline.repo_root, ["write-tree"], env=env).stdout.strip()


def _build_git_file_change_baseline(work_dir: Path) -> _GitFileChangeBaseline | None:
    object_dir: tempfile.TemporaryDirectory[str] | None = None
    try:
        repo_root_raw = _run_git(work_dir, ["rev-parse", "--show-toplevel"]).stdout.strip()
        repo_root = Path(repo_root_raw).resolve()
        alternate_object_dir_raw = _run_git(work_dir, ["rev-parse", "--git-path", "objects"]).stdout.strip()
        alternate_object_dir = Path(alternate_object_dir_raw)
        if not alternate_object_dir.is_absolute():
            alternate_object_dir = (work_dir / alternate_object_dir).resolve()
        rel = work_dir.resolve().relative_to(repo_root)
        pathspec = "." if str(rel) == "." else rel.as_posix()
        object_dir = tempfile.TemporaryDirectory(prefix="klaude-git-objects-")
        baseline = _GitFileChangeBaseline(
            repo_root=repo_root,
            pathspec=pathspec,
            object_dir=object_dir,
            alternate_object_dir=alternate_object_dir,
        )
        baseline.tree = _snapshot_git_worktree_tree(baseline)
        return baseline
    except (OSError, subprocess.CalledProcessError, ValueError):
        if object_dir is not None:
            object_dir.cleanup()
        return None


def _parse_git_numstat(output: bytes) -> dict[bytes, FileDiffStats]:
    stats_by_path: dict[bytes, FileDiffStats] = {}
    for record in output.split(b"\0"):
        if not record:
            continue
        parts = record.split(b"\t", 2)
        if len(parts) != 3:
            continue
        added_raw, removed_raw, path = parts
        added = int(added_raw) if added_raw.isdigit() else 0
        removed = int(removed_raw) if removed_raw.isdigit() else 0
        stats_by_path[path] = FileDiffStats(added=added, removed=removed)
    return stats_by_path


def _parse_git_name_status(output: bytes) -> dict[bytes, bytes]:
    parts = [part for part in output.split(b"\0") if part]
    statuses: dict[bytes, bytes] = {}
    for idx in range(0, len(parts) - 1, 2):
        status = parts[idx]
        path = parts[idx + 1]
        statuses[path] = status
    return statuses


def _build_git_file_changes(baseline: _GitFileChangeBaseline) -> list[TaskFileChange]:
    current_tree = _snapshot_git_worktree_tree(baseline)
    if current_tree == baseline.tree:
        return []

    diff_args = [baseline.tree, current_tree, "--", *_git_file_change_pathspecs(baseline.pathspec)]
    env = _git_env(baseline)
    name_status = _run_git_bytes(
        baseline.repo_root,
        ["diff", "--name-status", "--no-renames", "-z", *diff_args],
        env=env,
    ).stdout
    numstat = _run_git_bytes(
        baseline.repo_root,
        ["diff", "--numstat", "--no-renames", "-z", *diff_args],
        env=env,
    ).stdout

    statuses = _parse_git_name_status(name_status)
    stats_by_path = _parse_git_numstat(numstat)
    paths = sorted(set(statuses) | set(stats_by_path))

    changes: list[TaskFileChange] = []
    for path in paths:
        status = statuses.get(path, b"M")
        stats = stats_by_path.get(path, FileDiffStats())
        created = status.startswith(b"A")
        deleted = status.startswith(b"D")
        changes.append(
            TaskFileChange(
                path=str((baseline.repo_root / os.fsdecode(path)).resolve(strict=False)),
                added=stats.added,
                removed=stats.removed,
                created=created,
                edited=not created and not deleted,
                deleted=deleted,
            )
        )
    return changes


def _record_file_changes(file_change_summary: FileChangeSummary, changes: list[TaskFileChange]) -> None:
    for change in changes:
        if change.created:
            file_change_summary.record_created(change.path)
        elif change.deleted:
            file_change_summary.record_deleted(change.path)
        else:
            file_change_summary.record_edited(change.path)
        file_change_summary.add_diff(added=change.added, removed=change.removed, path=change.path)


@register(tools.BASH)
class BashTool(ToolABC):
    @classmethod
    def schema(cls) -> llm_param.ToolSchema:
        return llm_param.ToolSchema(
            name=tools.BASH,
            type="function",
            description=load_desc(Path(__file__).parent / "bash_tool.md"),
            parameters={
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The bash command to run",
                    },
                    "description": {
                        "type": "string",
                        "description": (
                            "Clear, concise description of what this command does in active voice. "
                            "This field is displayed to the user, so write it in the same language "
                            "the user is using (e.g. Chinese if the user writes in Chinese, "
                            "Japanese if the user writes in Japanese). "
                            'Never use words like "complex" or "risk" in the description - just describe '
                            "what it does."
                        ),
                    },
                    "timeout_ms": {
                        "type": "integer",
                        "description": f"The timeout for the command in milliseconds, default is {BASH_DEFAULT_TIMEOUT_MS}",
                        "default": BASH_DEFAULT_TIMEOUT_MS,
                    },
                },
                "required": ["command"],
            },
        )

    class BashArguments(BaseModel):
        command: str
        description: str | None = None
        timeout_ms: int = BASH_DEFAULT_TIMEOUT_MS

    @classmethod
    async def call(cls, arguments: str, context: ToolContext) -> message.ToolResultMessage:
        try:
            args = BashTool.BashArguments.model_validate_json(arguments)
        except ValueError as e:
            return message.ToolResultMessage(
                status="error",
                output_text=f"Invalid arguments: {e}",
            )
        return await cls.call_with_args(args, context)

    @classmethod
    async def call_with_args(cls, args: BashArguments, context: ToolContext) -> message.ToolResultMessage:
        # Safety check: only execute commands proven as "known safe"
        result = is_safe_command(args.command, work_dir=str(context.work_dir))
        if not result.is_safe:
            return message.ToolResultMessage(
                status="error",
                output_text=f"Command rejected: {result.error_msg}",
            )

        # Run the command using bash -lc so shell semantics work (pipes, &&, etc.)
        # Capture stdout/stderr, respect timeout, and return a ToolMessage.
        #
        # Important: this tool is intentionally non-interactive.
        # - Always detach stdin (DEVNULL) so interactive programs can't steal REPL input.
        # - Always disable pagers/editors to avoid launching TUI subprocesses that can
        #   leave the terminal in a bad state.
        cmd = ["bash", "-lc", args.command]
        timeout_sec = max(0.0, args.timeout_ms / 1000.0)

        env = os.environ.copy()
        env.update(
            {
                # Avoid blocking on git/jj prompts.
                "GIT_TERMINAL_PROMPT": "0",
                # Avoid pagers.
                "PAGER": "cat",
                "GIT_PAGER": "cat",
                # Avoid opening editors.
                "EDITOR": "true",
                "VISUAL": "true",
                "GIT_EDITOR": "true",
                "JJ_EDITOR": "true",
                # Encourage non-interactive output.
                "TERM": "dumb",
                # Make Python CLI scripts flush progress output even when stdout is not a TTY.
                "PYTHONUNBUFFERED": "1",
            }
        )

        file_tracker = context.file_tracker
        emit_tool_output_delta = context.emit_tool_output_delta

        def _hash_file_content_sha256(file_path: str) -> str | None:
            try:
                import hashlib

                suffix = Path(file_path).suffix.lower()
                if suffix in {".png", ".jpg", ".jpeg", ".gif", ".webp"}:
                    with open(file_path, "rb") as f:
                        return hashlib.sha256(f.read()).hexdigest()

                hasher = hashlib.sha256()
                with open(file_path, encoding="utf-8", errors="replace") as f:
                    for line in f:
                        hasher.update(line.encode("utf-8"))
                return hasher.hexdigest()
            except (FileNotFoundError, IsADirectoryError, OSError, PermissionError, UnicodeDecodeError):
                return None

        def _resolve_in_dir(base_dir: str, path: str) -> str:
            if os.path.isabs(path):
                return os.path.abspath(path)
            return os.path.abspath(os.path.join(base_dir, path))

        def _track_files_read(file_paths: list[str], *, base_dir: str) -> None:
            for p in file_paths:
                abs_path = _resolve_in_dir(base_dir, p)
                if not os.path.exists(abs_path) or os.path.isdir(abs_path):
                    continue
                sha = _hash_file_content_sha256(abs_path)
                if sha is None:
                    continue
                existing = file_tracker.get(abs_path)
                is_mem = existing.is_memory if existing else False
                is_skill = existing.is_skill if existing else False
                is_dir = existing.is_directory if existing else False
                with contextlib.suppress(Exception):
                    file_tracker[abs_path] = FileStatus(
                        mtime=Path(abs_path).stat().st_mtime,
                        content_sha256=sha,
                        is_memory=is_mem,
                        is_skill=is_skill,
                        skill_attachment_source=None,
                        is_directory=is_dir,
                    )

        def _track_files_written(file_paths: list[str], *, base_dir: str) -> None:
            # Same as read tracking, but intentionally kept separate for clarity.
            _track_files_read(file_paths, base_dir=base_dir)

        def _track_mv(src_paths: list[str], dest_path: str, *, base_dir: str) -> None:
            abs_dest = _resolve_in_dir(base_dir, dest_path)
            dest_is_dir = os.path.isdir(abs_dest)

            for src in src_paths:
                abs_src = _resolve_in_dir(base_dir, src)
                abs_new = os.path.join(abs_dest, os.path.basename(abs_src)) if dest_is_dir else abs_dest

                # Remove old entry if present.
                existing = file_tracker.pop(abs_src, None)
                is_mem = existing.is_memory if existing else False
                is_skill = existing.is_skill if existing else False
                is_dir = existing.is_directory if existing else False

                if not os.path.exists(abs_new) or os.path.isdir(abs_new):
                    continue

                sha = _hash_file_content_sha256(abs_new)
                if sha is None:
                    continue
                with contextlib.suppress(Exception):
                    file_tracker[abs_new] = FileStatus(
                        mtime=Path(abs_new).stat().st_mtime,
                        content_sha256=sha,
                        is_memory=is_mem,
                        is_skill=is_skill,
                        skill_attachment_source=None,
                        is_directory=is_dir,
                    )

        def _best_effort_update_file_tracker(command: str) -> None:
            # Best-effort heuristics for common shell tools that access/modify files.
            # We intentionally do not try to interpret complex shell scripts here.
            try:
                argv = shlex.split(command, posix=True)
            except ValueError:
                return
            if not argv:
                return

            # Handle common patterns like: cd subdir && cat file
            base_dir = str(context.work_dir)
            while len(argv) >= 4 and argv[0] == "cd" and argv[2] == "&&":
                dest = argv[1]
                if dest != "-":
                    base_dir = _resolve_in_dir(base_dir, dest)
                argv = argv[3:]
                if not argv:
                    return

            cmd0 = argv[0]
            if cmd0 == "cat":
                paths = [a for a in argv[1:] if a and not a.startswith("-") and a != "-"]
                _track_files_read(paths, base_dir=base_dir)
                return

            if cmd0 == "sed":
                # Support: sed [-i ...] 's/old/new/' file1 [file2 ...]
                # and: sed -n 'Np' file
                saw_script = False
                file_paths: list[str] = []
                for a in argv[1:]:
                    if not a:
                        continue
                    if a == "--":
                        continue
                    if a.startswith("-") and not saw_script:
                        continue
                    if not saw_script and (a.startswith("s/") or a.startswith("s|") or a.endswith("p")):
                        saw_script = True
                        continue
                    if saw_script and not a.startswith("-"):
                        file_paths.append(a)

                if file_paths:
                    _track_files_written(file_paths, base_dir=base_dir)
                return

            if cmd0 == "mv":
                # Support: mv [opts] src... dest
                operands: list[str] = []
                end_of_opts = False
                for a in argv[1:]:
                    if not end_of_opts and a == "--":
                        end_of_opts = True
                        continue
                    if not end_of_opts and a.startswith("-"):
                        continue
                    operands.append(a)
                if len(operands) < 2:
                    return
                srcs = operands[:-1]
                dest = operands[-1]
                _track_mv(srcs, dest, base_dir=base_dir)
                return

        async def _terminate_process(proc: asyncio.subprocess.Process) -> None:
            # Best-effort termination. Ensure we don't hang on cancellation.
            if proc.returncode is not None:
                return

            try:
                if os.name == "posix":
                    os.killpg(proc.pid, signal.SIGTERM)
                else:
                    proc.terminate()
            except ProcessLookupError:
                return
            except OSError:
                # Fall back to kill below.
                pass

            with contextlib.suppress(Exception):
                await asyncio.wait_for(proc.wait(), timeout=BASH_TERMINATE_TIMEOUT_SEC)
                return

            # Escalate to hard kill if it didn't exit quickly.
            with contextlib.suppress(Exception):
                if os.name == "posix":
                    os.killpg(proc.pid, signal.SIGKILL)
                else:
                    proc.kill()
            with contextlib.suppress(Exception):
                await asyncio.wait_for(proc.wait(), timeout=BASH_TERMINATE_TIMEOUT_SEC)

        async def _emit_output_delta(content: str) -> None:
            if emit_tool_output_delta is None or not content:
                return
            await emit_tool_output_delta(content)

        def _read_available_text(temp_file: Any, *, offset: int) -> tuple[str, int]:
            temp_file.flush()
            temp_file.seek(offset)
            data = temp_file.read()
            next_offset = temp_file.tell()
            if not data:
                return "", next_offset
            return _ANSI_ESCAPE_RE.sub("", data.decode(errors="replace")), next_offset

        git_file_change_baseline: _GitFileChangeBaseline | None = None
        if context.file_change_summary is not None:
            git_file_change_baseline = await asyncio.to_thread(_build_git_file_change_baseline, context.work_dir)

        async def _record_git_file_changes() -> None:
            if git_file_change_baseline is None or context.file_change_summary is None:
                return
            with contextlib.suppress(OSError, subprocess.CalledProcessError):
                changes = await asyncio.to_thread(_build_git_file_changes, git_file_change_baseline)
                _record_file_changes(context.file_change_summary, changes)

        try:
            # Create a dedicated process group so we can terminate the whole tree.
            # (macOS/Linux support start_new_session; Windows does not.)
            #
            # Use temp files instead of PIPE for stdout/stderr to avoid hanging
            # on background processes. With pipes, communicate() waits for EOF
            # which only arrives when ALL holders of the write end close it.
            # Background processes (cmd &) inherit pipe fds, so communicate()
            # blocks even after the shell exits. Temp files sidestep this:
            # proc.wait() returns as soon as the shell itself exits.
            with tempfile.TemporaryFile() as stdout_tmp, tempfile.TemporaryFile() as stderr_tmp:
                kwargs: dict[str, Any] = {
                    "stdin": asyncio.subprocess.DEVNULL,
                    "stdout": stdout_tmp,
                    "stderr": stderr_tmp,
                    "env": env,
                    "cwd": str(context.work_dir),
                }
                if os.name == "posix":
                    kwargs["start_new_session"] = True
                elif os.name == "nt":  # pragma: no cover
                    kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)

                proc = await asyncio.create_subprocess_exec(*cmd, **kwargs)
                deadline = asyncio.get_running_loop().time() + timeout_sec
                stdout_offset = 0
                stderr_offset = 0
                stdout_chunks: list[str] = []
                stderr_chunks: list[str] = []
                try:
                    while True:
                        remaining = deadline - asyncio.get_running_loop().time()
                        if remaining <= 0:
                            raise TimeoutError
                        try:
                            await asyncio.wait_for(proc.wait(), timeout=min(_STREAM_POLL_INTERVAL_SEC, remaining))
                            break
                        except TimeoutError:
                            pass

                        stdout_chunk, stdout_offset = _read_available_text(stdout_tmp, offset=stdout_offset)
                        stderr_chunk, stderr_offset = _read_available_text(stderr_tmp, offset=stderr_offset)
                        if stdout_chunk:
                            stdout_chunks.append(stdout_chunk)
                            await _emit_output_delta(stdout_chunk)
                        if stderr_chunk:
                            stderr_chunks.append(stderr_chunk)
                            await _emit_output_delta(stderr_chunk)

                    stdout_chunk, stdout_offset = _read_available_text(stdout_tmp, offset=stdout_offset)
                    stderr_chunk, stderr_offset = _read_available_text(stderr_tmp, offset=stderr_offset)
                    if stdout_chunk:
                        stdout_chunks.append(stdout_chunk)
                        await _emit_output_delta(stdout_chunk)
                    if stderr_chunk:
                        stderr_chunks.append(stderr_chunk)
                        await _emit_output_delta(stderr_chunk)
                except TimeoutError:
                    # Read any remaining output before terminating.
                    stdout_chunk, stdout_offset = _read_available_text(stdout_tmp, offset=stdout_offset)
                    stderr_chunk, stderr_offset = _read_available_text(stderr_tmp, offset=stderr_offset)
                    if stdout_chunk:
                        stdout_chunks.append(stdout_chunk)
                    if stderr_chunk:
                        stderr_chunks.append(stderr_chunk)

                    with contextlib.suppress(Exception):
                        await _terminate_process(proc)

                    await _record_git_file_changes()

                    timeout_header = f"Timeout after {args.timeout_ms} ms running: {args.command}"
                    collected_stdout = "".join(stdout_chunks).rstrip("\n")
                    collected_stderr = "".join(stderr_chunks).rstrip("\n")
                    parts = [timeout_header]
                    if collected_stdout:
                        parts.append(f"[stdout before timeout]\n{collected_stdout}")
                    if collected_stderr:
                        parts.append(f"[stderr before timeout]\n{collected_stderr}")
                    return message.ToolResultMessage(
                        status="error",
                        output_text="\n".join(parts),
                    )
                except asyncio.CancelledError:
                    # Ensure subprocess is stopped and propagate cancellation.
                    with contextlib.suppress(Exception):
                        await asyncio.shield(_terminate_process(proc))
                    raise

            stdout = "".join(stdout_chunks)
            stderr = "".join(stderr_chunks)
            rc = proc.returncode
            await _record_git_file_changes()

            if rc == 0:
                output = stdout
                # Include stderr if there is useful diagnostics despite success
                if stderr.strip():
                    output = (output + ("\n" if output else "")) + f"[stderr]\n{stderr}"

                _best_effort_update_file_tracker(args.command)
                return message.ToolResultMessage(
                    status="success",
                    # Preserve leading whitespace for tools like `nl -ba`.
                    # Only trim trailing newlines to avoid adding an extra blank line in the UI.
                    output_text=output.rstrip("\n"),
                )
            else:
                await _emit_output_delta(f"\nCommand exited with code {rc}\n")
                combined = ""
                if stdout.strip():
                    combined += f"[stdout]\n{stdout}\n"
                if stderr.strip():
                    combined += f"[stderr]\n{stderr}"
                if not combined:
                    combined = f"Command exited with code {rc}"
                return message.ToolResultMessage(
                    status="success",
                    # Preserve leading whitespace; only trim trailing newlines.
                    output_text=combined.rstrip("\n"),
                )
        except FileNotFoundError:
            return message.ToolResultMessage(
                status="error",
                output_text="bash not found on system path",
            )
        except asyncio.CancelledError:
            # Propagate cooperative cancellation so outer layers can handle interrupts correctly.
            raise
        except OSError as e:  # safeguard: catch remaining OS-level errors (permissions, resources, etc.)
            return message.ToolResultMessage(
                status="error",
                output_text=f"Execution error: {e}",
            )
        finally:
            if git_file_change_baseline is not None:
                git_file_change_baseline.object_dir.cleanup()
