import asyncio
import subprocess
from pathlib import Path

from pydantic import BaseModel

from klaude_code import const
from klaude_code.core.tool.shell.command_safety import is_safe_command, strip_bash_lc
from klaude_code.core.tool.tool_abc import ToolABC, load_desc
from klaude_code.core.tool.tool_registry import register
from klaude_code.protocol import llm_parameter, model, tools


@register(tools.BASH)
class BashTool(ToolABC):
    @classmethod
    def schema(cls) -> llm_parameter.ToolSchema:
        return llm_parameter.ToolSchema(
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
        command_str = strip_bash_lc(args.command)

        # Safety check: only execute commands proven as "known safe"
        result = is_safe_command(command_str)
        if not result.is_safe:
            return model.ToolResultItem(
                status="error",
                output=f"Command rejected: {result.error_msg}",
            )

        # Run the command using bash -lc so shell semantics work (pipes, &&, etc.)
        # Capture stdout/stderr, respect timeout, and return a ToolMessage.
        cmd = ["bash", "-lc", command_str]
        timeout_sec = max(0.0, args.timeout_ms / 1000.0)

        try:
            completed = await asyncio.to_thread(
                subprocess.run,
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout_sec,
                check=False,
            )

            stdout = completed.stdout or ""
            stderr = completed.stderr or ""
            rc = completed.returncode

            if rc == 0:
                output = stdout if stdout else ""
                # Include stderr if there is useful diagnostics despite success
                if stderr.strip():
                    output = (output + ("\n" if output else "")) + f"[stderr]\n{stderr}"
                return model.ToolResultItem(
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
                return model.ToolResultItem(
                    status="error",
                    output=combined.strip(),
                )

        except subprocess.TimeoutExpired:
            return model.ToolResultItem(
                status="error",
                output=f"Timeout after {args.timeout_ms} ms running: {command_str}",
            )
        except FileNotFoundError:
            return model.ToolResultItem(
                status="error",
                output="bash not found on system path",
            )
        except Exception as e:  # safeguard against unexpected failures
            return model.ToolResultItem(
                status="error",
                output=f"Execution error: {e}",
            )
