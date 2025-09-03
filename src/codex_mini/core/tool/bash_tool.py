import re
import shlex

from pydantic import BaseModel

from codex_mini.core.tool.tool_abc import ToolABC
from codex_mini.core.tool.tool_common import truncate_tool_output
from codex_mini.core.tool.tool_registry import register
from codex_mini.protocol.llm_parameter import ToolSchema
from codex_mini.protocol.model import ContentPart, ToolMessage

BASH_TOOL_NAME = "Bash"


def _is_valid_sed_n_arg(s: str | None) -> bool:
    if not s:
        return False
    # Matches: Np or M,Np where M,N are positive integers
    return bool(re.fullmatch(r"\d+(,\d+)?p", s))


def _is_safe_to_call_with_exec(argv: list[str]) -> bool:
    if not argv:
        return False

    cmd0 = argv[0]

    # simple allowlist
    if cmd0 in {
        "cat",
        "cd",
        "echo",
        "false",
        "grep",
        "head",
        "ls",
        "nl",
        "pwd",
        "tail",
        "true",
        "wc",
        "which",
    }:
        return True

    if cmd0 == "find":
        unsafe_opts = {
            "-exec",
            "-execdir",
            "-ok",
            "-okdir",
            "-delete",
            "-fls",
            "-fprint",
            "-fprint0",
            "-fprintf",
        }
        return not any(arg in unsafe_opts for arg in argv[1:])

    if cmd0 == "rg":
        unsafe_noarg = {"--search-zip", "-z"}
        unsafe_witharg_prefix = {"--pre", "--hostname-bin"}

        for i, arg in enumerate(argv[1:], start=1):
            if arg in unsafe_noarg:
                return False
            for opt in unsafe_witharg_prefix:
                if arg == opt:
                    return False
                if arg.startswith(opt + "="):
                    return False
        return True

    if cmd0 == "git":
        sub = argv[1] if len(argv) > 1 else None
        return sub in {"branch", "status", "log", "diff", "show"}

    if cmd0 == "cargo":
        return len(argv) > 1 and argv[1] == "check"

    if cmd0 == "sed":
        if (
            len(argv) == 4
            and argv[1] == "-n"
            and _is_valid_sed_n_arg(argv[2])
            and bool(argv[3])
        ):
            return True
        return False

    return False


def _contains_disallowed_shell_syntax(script: str) -> bool:
    # Disallow subshells, command substitution, and redirections.
    # Conservative: detect raw chars; may reject some safe-but-quoted cases.
    disallowed_patterns = [
        r"[()]",  # subshells
        r"`",  # backticks
        r"\$\(",  # command substitution
        r"[<>]",  # redirection
        r"\|&",  # pipe stdout+stderr
    ]
    for pat in disallowed_patterns:
        if re.search(pat, script):
            return True
    return False


def _parse_word_only_commands_sequence(script: str) -> list[list[str]] | None:
    if not script or _contains_disallowed_shell_syntax(script):
        return None

    # Split by allowed operators: &&, ||, ;, |
    parts = re.split(r"\s*(?:\|\||&&|;|\|)\s*", script)
    commands: list[list[str]] = []
    try:
        for part in parts:
            if not part.strip():
                return None
            argv = shlex.split(part, posix=True)
            if not argv:
                return None
            commands.append(argv)
    except ValueError:
        return None
    return commands


def is_safe_command(command: str) -> bool:
    """Conservatively determine if a command is known-safe.

    Mirrors the logic of the Rust `is_known_safe_command` with a simplified
    parser for bash -lc scripts. Returns True only when safe is provable.
    """
    # First, try direct exec-style argv safety (e.g., "ls -l").
    try:
        argv = shlex.split(command, posix=True)
    except ValueError:
        argv = []

    if argv and _is_safe_to_call_with_exec(argv):
        return True

    # Next, allow scripts that are sequences of safe commands joined by
    # allowed operators (&&, ||, ;, |) with no redirections or subshells.
    seq = _parse_word_only_commands_sequence(command)
    if seq and all(_is_safe_to_call_with_exec(cmd) for cmd in seq):
        return True

    return False


@register(BASH_TOOL_NAME)
class BashTool(ToolABC):
    @classmethod
    def schema(cls) -> ToolSchema:
        return ToolSchema(
            name=BASH_TOOL_NAME,
            type="function",
            description="""Runs a shell command and returns its output.

# Usage Notes
Allowed commands:
- cat/cd/echo/grep/ls/nl/pwd/tail/true/false/wc/which
- git (branch/status/log/diff/show);
- cargo check;
- find (without -exec/-delete/-f* print options);
- rg (without --pre/--hostname-bin/--search-zip/-z);
- sequences joined by &&, ||, ;, |.
Disallow redirection, subshells/parentheses, and command substitution.""",
            parameters={
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The bash command to run",
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

    class BashArguments(BaseModel):
        command: str
        timeout_ms: int = 60000

    @classmethod
    async def call(cls, arguments: str) -> ToolMessage:
        try:
            args = BashTool.BashArguments.model_validate_json(arguments)
        except ValueError as e:
            return ToolMessage(
                status="error",
                content=[ContentPart(text=f"Invalid arguments: {e}")],
            )
        # Safety check: only execute commands proven as "known safe"
        if not is_safe_command(args.command):
            return ToolMessage(
                status="error",
                content=[
                    ContentPart(
                        text=(
                            "Command rejected as not known-safe. Allowed: cat/cd/echo/grep/ls/nl/pwd/tail/true/false/wc/which; "
                            "git (branch/status/log/diff/show); cargo check; find (without -exec/-delete/-f* print options); "
                            "rg (without --pre/--hostname-bin/--search-zip/-z); sequences joined by &&, ||, ;, |. "
                            "Disallow redirection, subshells/parentheses, and command substitution."
                        )
                    )
                ],
            )
        # Run the command using bash -lc so shell semantics work (pipes, &&, etc.)
        # Capture stdout/stderr, respect timeout, and return a ToolMessage.
        import asyncio
        import subprocess

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

            stdout = completed.stdout or ""
            stderr = completed.stderr or ""
            rc = completed.returncode

            if rc == 0:
                output = stdout if stdout else ""
                # Include stderr if there is useful diagnostics despite success
                if stderr.strip():
                    output = (output + ("\n" if output else "")) + f"[stderr]\n{stderr}"
                output = truncate_tool_output(output)
                return ToolMessage(
                    status="success",
                    content=[ContentPart(text=output.strip())]
                    if output
                    else [ContentPart(text="")],
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
                return ToolMessage(
                    status="error",
                    content=[ContentPart(text=combined.strip())],
                )

        except subprocess.TimeoutExpired:
            return ToolMessage(
                status="error",
                content=[
                    ContentPart(
                        text=(
                            f"Timeout after {args.timeout_ms} ms running: {args.command}"
                        )
                    )
                ],
            )
        except FileNotFoundError:
            return ToolMessage(
                status="error",
                content=[ContentPart(text="bash not found on system path")],
            )
        except Exception as e:  # safeguard against unexpected failures
            return ToolMessage(
                status="error",
                content=[ContentPart(text=f"Execution error: {e}")],
            )
