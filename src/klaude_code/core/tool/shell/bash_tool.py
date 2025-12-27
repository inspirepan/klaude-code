import asyncio
import contextlib
import os
import re
import shlex
import signal
import subprocess
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from klaude_code import const
from klaude_code.core.tool.shell.command_safety import is_safe_command
from klaude_code.core.tool.tool_abc import ToolABC, load_desc
from klaude_code.core.tool.tool_context import get_current_file_tracker
from klaude_code.core.tool.tool_registry import register
from klaude_code.protocol import llm_param, model, tools

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
                    "timeout_ms": {
                        "type": "integer",
                        "description": f"The timeout for the command in milliseconds, default is {const.BASH_DEFAULT_TIMEOUT_MS}",
                        "default": const.BASH_DEFAULT_TIMEOUT_MS,
                    },
                },
                "required": ["command"],
            },
        )

    class BashArguments(BaseModel):
        command: str
        timeout_ms: int = const.BASH_DEFAULT_TIMEOUT_MS

    @classmethod
    async def call(cls, arguments: str) -> model.ToolResultItem:
        try:
            args = BashTool.BashArguments.model_validate_json(arguments)
        except ValueError as e:
            return model.ToolResultItem(
                status="error",
                output=f"Invalid arguments: {e}",
            )
        return await cls.call_with_args(args)

    @classmethod
    async def call_with_args(cls, args: BashArguments) -> model.ToolResultItem:
        # Safety check: only execute commands proven as "known safe"
        result = is_safe_command(args.command)
        if not result.is_safe:
            return model.ToolResultItem(
                status="error",
                output=f"Command rejected: {result.error_msg}",
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
            }
        )

        def _hash_file_content_sha256(file_path: str) -> str | None:
            try:
                suffix = Path(file_path).suffix.lower()
                if suffix in {".png", ".jpg", ".jpeg", ".gif", ".webp"}:
                    import hashlib

                    with open(file_path, "rb") as f:
                        return hashlib.sha256(f.read()).hexdigest()

                import hashlib

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
            file_tracker = get_current_file_tracker()
            if file_tracker is None:
                return
            for p in file_paths:
                abs_path = _resolve_in_dir(base_dir, p)
                if not os.path.exists(abs_path) or os.path.isdir(abs_path):
                    continue
                sha = _hash_file_content_sha256(abs_path)
                if sha is None:
                    continue
                existing = file_tracker.get(abs_path)
                is_mem = existing.is_memory if existing else False
                with contextlib.suppress(Exception):
                    file_tracker[abs_path] = model.FileStatus(
                        mtime=Path(abs_path).stat().st_mtime,
                        content_sha256=sha,
                        is_memory=is_mem,
                    )

        def _track_files_written(file_paths: list[str], *, base_dir: str) -> None:
            # Same as read tracking, but intentionally kept separate for clarity.
            _track_files_read(file_paths, base_dir=base_dir)

        def _track_mv(src_paths: list[str], dest_path: str, *, base_dir: str) -> None:
            file_tracker = get_current_file_tracker()
            if file_tracker is None:
                return

            abs_dest = _resolve_in_dir(base_dir, dest_path)
            dest_is_dir = os.path.isdir(abs_dest)

            for src in src_paths:
                abs_src = _resolve_in_dir(base_dir, src)
                abs_new = os.path.join(abs_dest, os.path.basename(abs_src)) if dest_is_dir else abs_dest

                # Remove old entry if present.
                existing = file_tracker.pop(abs_src, None)
                is_mem = existing.is_memory if existing else False

                if not os.path.exists(abs_new) or os.path.isdir(abs_new):
                    continue

                sha = _hash_file_content_sha256(abs_new)
                if sha is None:
                    continue
                with contextlib.suppress(Exception):
                    file_tracker[abs_new] = model.FileStatus(
                        mtime=Path(abs_new).stat().st_mtime,
                        content_sha256=sha,
                        is_memory=is_mem,
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
            base_dir = os.getcwd()
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
                await asyncio.wait_for(proc.wait(), timeout=1.0)
                return

            # Escalate to hard kill if it didn't exit quickly.
            with contextlib.suppress(Exception):
                if os.name == "posix":
                    os.killpg(proc.pid, signal.SIGKILL)
                else:
                    proc.kill()
            with contextlib.suppress(Exception):
                await asyncio.wait_for(proc.wait(), timeout=1.0)

        try:
            # Create a dedicated process group so we can terminate the whole tree.
            # (macOS/Linux support start_new_session; Windows does not.)
            kwargs: dict[str, Any] = {
                "stdin": asyncio.subprocess.DEVNULL,
                "stdout": asyncio.subprocess.PIPE,
                "stderr": asyncio.subprocess.PIPE,
                "env": env,
            }
            if os.name == "posix":
                kwargs["start_new_session"] = True
            elif os.name == "nt":  # pragma: no cover
                kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)

            proc = await asyncio.create_subprocess_exec(*cmd, **kwargs)
            try:
                stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout_sec)
            except TimeoutError:
                with contextlib.suppress(Exception):
                    await _terminate_process(proc)
                return model.ToolResultItem(
                    status="error",
                    output=f"Timeout after {args.timeout_ms} ms running: {args.command}",
                )
            except asyncio.CancelledError:
                # Ensure subprocess is stopped and propagate cancellation.
                with contextlib.suppress(Exception):
                    await asyncio.shield(_terminate_process(proc))
                raise

            stdout = _ANSI_ESCAPE_RE.sub("", (stdout_b or b"").decode(errors="replace"))
            stderr = _ANSI_ESCAPE_RE.sub("", (stderr_b or b"").decode(errors="replace"))
            rc = proc.returncode

            if rc == 0:
                output = stdout if stdout else ""
                # Include stderr if there is useful diagnostics despite success
                if stderr.strip():
                    output = (output + ("\n" if output else "")) + f"[stderr]\n{stderr}"

                _best_effort_update_file_tracker(args.command)
                return model.ToolResultItem(
                    status="success",
                    # Preserve leading whitespace for tools like `nl -ba`.
                    # Only trim trailing newlines to avoid adding an extra blank line in the UI.
                    output=output.rstrip("\n"),
                )
            else:
                combined = ""
                if stdout.strip():
                    combined += f"[stdout]\n{stdout}\n"
                if stderr.strip():
                    combined += f"[stderr]\n{stderr}"
                if not combined:
                    combined = f"Command exited with code {rc}"
                return model.ToolResultItem(
                    status="error",
                    # Preserve leading whitespace; only trim trailing newlines.
                    output=combined.rstrip("\n"),
                )
        except FileNotFoundError:
            return model.ToolResultItem(
                status="error",
                output="bash not found on system path",
            )
        except asyncio.CancelledError:
            # Propagate cooperative cancellation so outer layers can handle interrupts correctly.
            raise
        except OSError as e:  # safeguard: catch remaining OS-level errors (permissions, resources, etc.)
            return model.ToolResultItem(
                status="error",
                output=f"Execution error: {e}",
            )
