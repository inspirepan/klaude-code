import asyncio
import re
import subprocess
from pathlib import Path

from pydantic import BaseModel

from klaude_code import const
from klaude_code.core.tool.shell.command_safety import is_safe_command
from klaude_code.core.tool.tool_abc import ToolABC, load_desc
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
        cmd = ["bash", "-lc", args.command]
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

            stdout = _ANSI_ESCAPE_RE.sub("", completed.stdout or "")
            stderr = _ANSI_ESCAPE_RE.sub("", completed.stderr or "")
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
                output=f"Timeout after {args.timeout_ms} ms running: {args.command}",
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
