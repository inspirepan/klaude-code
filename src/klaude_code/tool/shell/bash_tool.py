import asyncio
import codecs
import contextlib
import os
import tempfile
import time
from pathlib import Path

from pydantic import BaseModel, Field

from klaude_code.const import BASH_DEFAULT_TIMEOUT_MS, BASH_DEFAULT_WAIT_MS
from klaude_code.protocol import llm_param, message, tools
from klaude_code.protocol.models import BashUIExtra
from klaude_code.tool.core.abc import ToolABC, load_desc
from klaude_code.tool.core.ansi import strip_ansi
from klaude_code.tool.core.context import ToolContext
from klaude_code.tool.core.registry import register
from klaude_code.tool.shell.command_safety import is_safe_command
from klaude_code.tool.shell.file_tracking import ShellFileTracker
from klaude_code.tool.shell.task_manager import ShellTaskManager


def _build_interrupted_output(command: str, elapsed_seconds: float, stdout: str, stderr: str) -> str:
    parts = [f"Interrupted by user after {elapsed_seconds:.2f} seconds running: {command}"]
    if stdout.rstrip("\n"):
        parts.append(f"[stdout before interrupt]\n{stdout.rstrip(chr(10))}")
    if stderr.rstrip("\n"):
        parts.append(f"[stderr before interrupt]\n{stderr.rstrip(chr(10))}")
    return "\n".join(parts)


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
                    "command": {"type": "string", "description": "The bash command to run"},
                    "description": {
                        "type": "string",
                        "description": "Short active-voice description, within 32 terminal cells, in the user's language.",
                    },
                    "timeout_ms": {
                        "type": ["integer", "null"],
                        "minimum": 0,
                        "default": BASH_DEFAULT_TIMEOUT_MS,
                        "description": "Hard runtime limit in milliseconds, including background time. Default 1800000 (30 minutes). Set null explicitly for a dev server with no hard time limit.",
                    },
                    "wait_ms": {
                        "type": "integer",
                        "minimum": 0,
                        "default": BASH_DEFAULT_WAIT_MS,
                        "description": "Foreground wait window before the same process becomes a managed background task.",
                    },
                    "run_in_background": {
                        "type": "boolean",
                        "default": False,
                        "description": "Return a managed task ID immediately; requires the server-owned task manager.",
                    },
                },
                "required": ["command"],
            },
        )

    class BashArguments(BaseModel):
        command: str
        description: str | None = None
        timeout_ms: int | None = Field(default=BASH_DEFAULT_TIMEOUT_MS, ge=0)
        wait_ms: int = Field(default=BASH_DEFAULT_WAIT_MS, ge=0)
        run_in_background: bool = False

    @classmethod
    async def call(cls, arguments: str, context: ToolContext) -> message.ToolResultMessage:
        try:
            args = cls.BashArguments.model_validate_json(arguments)
        except ValueError as error:
            return message.ToolResultMessage(status="error", output_text=f"Invalid arguments: {error}")
        return await cls.call_with_args(args, context)

    @classmethod
    async def call_with_args(cls, args: BashArguments, context: ToolContext) -> message.ToolResultMessage:
        safety = is_safe_command(args.command, work_dir=str(context.work_dir))
        if not safety.is_safe:
            return message.ToolResultMessage(status="error", output_text=f"Command rejected: {safety.error_msg}")
        if args.run_in_background and context.shell_task_manager is None:
            return message.ToolResultMessage(
                status="error", output_text="Background execution requires a server-owned shell task manager."
            )
        env = os.environ.copy()
        env.update(
            {
                "GIT_TERMINAL_PROMPT": "0",
                "PAGER": "cat",
                "GIT_PAGER": "cat",
                "EDITOR": "true",
                "VISUAL": "true",
                "GIT_EDITOR": "true",
                "JJ_EDITOR": "true",
                "TERM": "dumb",
                "PYTHONUNBUFFERED": "1",
                "KLAUDE_SESSION_ID": context.session_id,
            }
        )
        temporary = tempfile.TemporaryDirectory() if context.shell_task_manager is None else None
        manager = context.shell_task_manager or ShellTaskManager(
            storage_root=Path(temporary.name) if temporary else None
        )
        task_id: str | None = None
        detached = False
        started = time.monotonic()
        stdout = ""
        stderr = ""
        offsets = {"stdout": 0, "stderr": 0}
        decoders = {name: codecs.getincrementaldecoder("utf-8")("replace") for name in offsets}

        def collect(*, final: bool = False) -> list[str]:
            nonlocal stdout, stderr
            chunks: list[str] = []
            if task_id is None:
                return chunks
            for name in offsets:
                data = manager.read_stream(context.session_id, task_id, name, offsets[name])
                offsets[name] += len(data)
                text = strip_ansi(decoders[name].decode(data, final=final))
                if name == "stdout":
                    stdout += text
                else:
                    stderr += text
                if text:
                    chunks.append(text)
            return chunks

        def interrupted() -> message.ToolResultMessage:
            collect()
            return message.ToolResultMessage(
                status="aborted",
                output_text=_build_interrupted_output(args.command, time.monotonic() - started, stdout, stderr),
            )

        async def background_result() -> message.ToolResultMessage:
            nonlocal detached
            assert task_id is not None
            detached = True
            snapshot = await manager.background_task(context.session_id, task_id)
            page = await manager.read_output(context.session_id, task_id)
            return message.ToolResultMessage(
                status="success",
                output_text=f"Shell task {task_id} is {snapshot.status} in background.\nUse ManageShell with this task_id for output, wait, or stop.\nOutput offset: {page.next_offset}\n{page.output}".rstrip(
                    "\n"
                ),
            )

        try:
            tracker = ShellFileTracker(context.file_tracker, context.work_dir)
            snapshot = await manager.start(
                session_id=context.session_id,
                work_dir=context.work_dir,
                command=args.command,
                description=args.description or "",
                timeout_ms=args.timeout_ms,
                env=env,
                background=False,
                on_success=lambda: tracker.update_from_command(args.command),
            )
            task_id = snapshot.task_id
            if context.register_tool_interrupt_result_getter is not None:
                context.register_tool_interrupt_result_getter(interrupted)
            if args.run_in_background:
                return await background_result()
            while True:
                remaining_ms = max(0, int(args.wait_ms - (time.monotonic() - started) * 1000))
                snapshot = await manager.wait_task(
                    context.session_id,
                    task_id,
                    wait_ms=min(50, remaining_ms) if context.shell_task_manager is not None else 50,
                )
                for chunk in collect():
                    if context.emit_tool_output_delta is not None:
                        await context.emit_tool_output_delta(chunk)
                if snapshot.status not in {"running", "stopping"}:
                    break
                if context.shell_task_manager is not None and time.monotonic() - started >= args.wait_ms / 1000:
                    # Set the guard before awaiting callbacks: cancellation after detach must not kill it.
                    return await background_result()
            for chunk in collect(final=True):
                if context.emit_tool_output_delta is not None:
                    await context.emit_tool_output_delta(chunk)
            if snapshot.status in {"timed_out", "stopped"} or snapshot.reason is not None:
                parts = [snapshot.reason or snapshot.status]
                if stdout:
                    parts.append(f"[stdout before timeout]\n{stdout.rstrip(chr(10))}")
                if stderr:
                    parts.append(f"[stderr before timeout]\n{stderr.rstrip(chr(10))}")
                return message.ToolResultMessage(status="error", output_text="\n".join(parts))
            rc = snapshot.exit_code if snapshot.exit_code is not None else 1
            if rc == 0:
                output = stdout + (("\n" if stdout else "") + f"[stderr]\n{stderr}" if stderr.strip() else "")
            else:
                output = f"Command exited with code {rc}\n"
                if stdout.strip():
                    output += f"[stdout]\n{stdout}\n"
                if stderr.strip():
                    output += f"[stderr]\n{stderr}"
                if context.emit_tool_output_delta is not None:
                    await context.emit_tool_output_delta(f"\nCommand exited with code {rc}\n")
            return message.ToolResultMessage(
                status="success", output_text=output.rstrip("\n"), ui_extra=BashUIExtra(exit_code=rc)
            )
        except asyncio.CancelledError:
            if task_id is None or detached:
                raise
            with contextlib.suppress(asyncio.CancelledError):
                await asyncio.shield(manager.stop_task(context.session_id, task_id))
            return interrupted()
        except (OSError, ValueError) as error:
            return message.ToolResultMessage(status="error", output_text=f"Execution error: {error}")
        finally:
            if task_id is not None and not detached:
                with contextlib.suppress(OSError, ValueError):
                    await manager.release_foreground(context.session_id, task_id)
            if temporary is not None:
                await manager.aclose()
                temporary.cleanup()
