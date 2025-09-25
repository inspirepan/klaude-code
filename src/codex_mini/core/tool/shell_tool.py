"""
For GPT-5-Codex
"""

import asyncio
import os
import subprocess

from pydantic import BaseModel

from codex_mini.core.tool.apply_patch_handler import ApplyPatchHandler
from codex_mini.core.tool.command_safety import is_safe_command, strip_bash_lc_argv
from codex_mini.core.tool.tool_abc import ToolABC
from codex_mini.core.tool.tool_common import truncate_tool_output
from codex_mini.core.tool.tool_registry import register
from codex_mini.protocol.llm_parameter import ToolSchema
from codex_mini.protocol.model import ToolResultItem
from codex_mini.protocol.tools import SHELL


@register(SHELL)
class ShellTool(ToolABC):
    @classmethod
    def schema(cls) -> ToolSchema:
        return ToolSchema(
            name=SHELL,
            type="function",
            description="""Runs a shell command and returns its output. Support apply_patch""",
            parameters={
                "type": "object",
                "properties": {
                    "command": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "The command to execute",
                    },
                    "workdir": {
                        "type": "string",
                        "description": "The working directory to execute the command in",
                        "default": ".",
                    },
                    "timeout_ms": {
                        "type": "integer",
                        "description": "The timeout for the command in milliseconds, default is 60000",
                        "default": 60000,
                    },
                },
                "required": ["command"],
            },
        )

    class ShellArguments(BaseModel):
        command: list[str]
        workdir: str = "."
        timeout_ms: int = 60000

    @classmethod
    async def call(cls, arguments: str) -> ToolResultItem:
        try:
            args = ShellTool.ShellArguments.model_validate_json(arguments)
        except ValueError as e:
            return ToolResultItem(
                status="error",
                output=f"Invalid arguments: {e}",
            )
        return await cls.call_with_args(args)

    @classmethod
    async def call_with_args(cls, args: ShellArguments) -> ToolResultItem:
        if not args.command:
            return ToolResultItem(
                status="error",
                output="No command provided",
            )
        # Validate and expand working directory
        workdir = await cls.get_workdir(args.workdir)

        # Check for apply patch command
        maybe_parse_result = ApplyPatchHandler.maybe_parse_apply_patch_command(args.command)
        if maybe_parse_result.is_apply_patch:
            assert maybe_parse_result.patch_text is not None
            return await ApplyPatchHandler.handle_apply_patch(maybe_parse_result.patch_text)

        # Strip bash -lc wrapper if present
        argv = strip_bash_lc_argv(args.command)

        # Safety check: directly use argv list for efficiency
        safety_result = is_safe_command(argv)
        if not safety_result.is_safe:
            return ToolResultItem(
                status="error",
                output=f"Command rejected: {safety_result.error_msg}",
            )

        # Run the command directly with the actual argv list
        timeout_sec = max(0.0, args.timeout_ms / 1000.0)
        cmd = ["bash", "-lc", " ".join(argv)]
        try:
            completed = await asyncio.to_thread(
                subprocess.run,
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout_sec,
                check=False,
                cwd=workdir,
            )

            stdout = completed.stdout or ""
            stderr = completed.stderr or ""
            rc = completed.returncode

            if rc == 0:
                output = stdout if stdout else ""
                # Include stderr if there is useful diagnostics despite success
                if stderr.strip():
                    output = (output + ("\n" if output else "")) + f"[stderr]\n{stderr}"
                output = truncate_tool_output(output)
                return ToolResultItem(
                    status="success",
                    output=output.strip(),
                )
            else:
                combined = ""
                if stdout.strip():
                    combined += f"[stdout]\n{stdout}\n"
                if stderr.strip():
                    combined += f"[stderr]\n{stderr}"
                if not combined:
                    combined = f"Command exited with code {rc}"
                combined = truncate_tool_output(combined)
                return ToolResultItem(
                    status="error",
                    output=combined.strip(),
                )

        except subprocess.TimeoutExpired:
            return ToolResultItem(
                status="error",
                output=f"Timeout after {args.timeout_ms} ms running: {' '.join(argv)}",
            )
        except FileNotFoundError:
            return ToolResultItem(
                status="error",
                output=f"Command not found: {argv[0] if argv else 'unknown'}",
            )
        except Exception as e:
            return ToolResultItem(
                status="error",
                output=f"Execution error: {e}",
            )

    @classmethod
    async def get_workdir(cls, arg_workdir: str) -> str:
        if arg_workdir.strip() == ".":
            workdir = os.getcwd()
        else:
            workdir = os.path.expanduser(arg_workdir)
            if not os.path.isabs(workdir):
                workdir = os.path.abspath(workdir)
            if not os.path.exists(workdir):
                raise ValueError(f"Working directory does not exist: {workdir}")
            if not os.path.isdir(workdir):
                raise ValueError(f"Working directory is not a directory: {workdir}")
        return workdir
