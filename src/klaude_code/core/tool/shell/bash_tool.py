import asyncio
import contextlib
import os
import re
import signal
import subprocess
from pathlib import Path
from typing import Any

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
            except Exception:
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
        except FileNotFoundError:
            return model.ToolResultItem(
                status="error",
                output="bash not found on system path",
            )
        except asyncio.CancelledError:
            # Propagate cooperative cancellation so outer layers can handle interrupts correctly.
            raise
        except Exception as e:  # safeguard against unexpected failures
            return model.ToolResultItem(
                status="error",
                output=f"Execution error: {e}",
            )
