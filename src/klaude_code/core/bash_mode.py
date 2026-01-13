"""Bash-mode execution helpers.

This module provides the implementation for running non-interactive shell commands
with streaming output to the UI, plus session history recording.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import re
import secrets
import shutil
import signal
import subprocess
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

from klaude_code.const import BASH_MODE_SESSION_OUTPUT_MAX_BYTES, BASH_TERMINATE_TIMEOUT_SEC, TOOL_OUTPUT_TRUNCATION_DIR
from klaude_code.core.tool.offload import offload_tool_output
from klaude_code.protocol import events, message
from klaude_code.session.session import Session


@dataclass(frozen=True)
class _BashModeToolCall:
    tool_name: str = "Bash"


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


def _format_inline_code(text: str) -> str:
    if not text:
        return "``"
    max_run = 0
    run = 0
    for ch in text:
        if ch == "`":
            run += 1
            max_run = max(max_run, run)
        else:
            run = 0
    fence = "`" * (max_run + 1)
    return f"{fence}{text}{fence}"


def _resolve_shell_command(command_text: str) -> list[str]:
    # Use the user's default shell when possible.
    # - macOS/Linux: $SHELL (supports bash/zsh/fish)
    # - Windows: prefer pwsh/powershell
    if sys.platform == "win32":  # pragma: no cover
        exe = "pwsh" if shutil.which("pwsh") else "powershell"
        return [exe, "-NoProfile", "-Command", command_text]

    shell_path = os.environ.get("SHELL")
    shell_name = Path(shell_path).name.lower() if shell_path else ""
    if shell_path and shell_name in {"bash", "zsh", "fish"}:
        # Use -lic to load both login profile and interactive config (e.g. aliases from .zshrc)
        return [shell_path, "-lic", command_text]
    return ["bash", "-lic", command_text]


async def _terminate_process(proc: asyncio.subprocess.Process) -> None:
    if proc.returncode is not None:
        return

    try:
        if os.name == "posix":
            os.killpg(proc.pid, signal.SIGTERM)
        else:  # pragma: no cover
            proc.terminate()
    except ProcessLookupError:
        return
    except OSError:
        pass

    with contextlib.suppress(Exception):
        await asyncio.wait_for(proc.wait(), timeout=BASH_TERMINATE_TIMEOUT_SEC)
        return

    with contextlib.suppress(Exception):
        if os.name == "posix":
            os.killpg(proc.pid, signal.SIGKILL)
        else:  # pragma: no cover
            proc.kill()
    with contextlib.suppress(Exception):
        await asyncio.wait_for(proc.wait(), timeout=BASH_TERMINATE_TIMEOUT_SEC)


async def _emit_clean_chunk(
    *,
    emit_event: Callable[[events.Event], Awaitable[None]],
    session_id: str,
    chunk: str,
    out_file: TextIO,
) -> None:
    if not chunk:
        return

    cleaned = _ANSI_ESCAPE_RE.sub("", chunk)
    if cleaned:
        await emit_event(events.BashCommandOutputDeltaEvent(session_id=session_id, content=cleaned))
        with contextlib.suppress(Exception):
            out_file.write(cleaned)


async def run_bash_command(
    *,
    emit_event: Callable[[events.Event], Awaitable[None]],
    session: Session,
    session_id: str,
    command: str,
) -> None:
    """Run a non-interactive bash command with streaming output to the UI.

    The full (cleaned) output is appended to session history in a single UserMessage
    as: `Ran <command>` plus truncated output via offload strategy.
    """

    await emit_event(events.BashCommandStartEvent(session_id=session_id, command=command))

    # Create a log file to support large outputs without holding everything in memory.
    # Use TOOL_OUTPUT_TRUNCATION_DIR (system temp) for consistency with offload.
    tmp_root = Path(TOOL_OUTPUT_TRUNCATION_DIR)
    tmp_root.mkdir(parents=True, exist_ok=True)
    log_path = tmp_root / f"klaude-bash-mode-{secrets.token_hex(8)}.log"

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
        }
    )

    proc: asyncio.subprocess.Process | None = None
    cancelled = False
    exit_code: int | None = None

    # Hold back any trailing ESC-started sequence to avoid leaking control codes
    # when the subprocess output is chunked.
    pending = ""

    try:
        kwargs: dict[str, object] = {
            "stdin": asyncio.subprocess.DEVNULL,
            "stdout": asyncio.subprocess.PIPE,
            "stderr": asyncio.subprocess.STDOUT,
            "env": env,
        }
        if os.name == "posix":
            kwargs["start_new_session"] = True
        elif os.name == "nt":  # pragma: no cover
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)

        shell_argv = _resolve_shell_command(command)
        proc = await asyncio.create_subprocess_exec(*shell_argv, **kwargs)  # type: ignore[arg-type]
        assert proc.stdout is not None

        with log_path.open("w", encoding="utf-8", errors="replace") as out_file:
            while True:
                data = await proc.stdout.read(4096)
                if not data:
                    break
                piece = data.decode(errors="replace")
                pending += piece

                # Keep from the last ESC onwards to avoid emitting incomplete sequences.
                last_esc = pending.rfind("\x1b")
                if last_esc == -1:
                    to_emit, pending = pending, ""
                elif last_esc < len(pending) - 128:
                    to_emit, pending = pending[:last_esc], pending[last_esc:]
                else:
                    # Wait for more bytes to complete the sequence.
                    continue

                await _emit_clean_chunk(
                    emit_event=emit_event,
                    session_id=session_id,
                    chunk=to_emit,
                    out_file=out_file,
                )

            if pending:
                await _emit_clean_chunk(
                    emit_event=emit_event,
                    session_id=session_id,
                    chunk=pending,
                    out_file=out_file,
                )
                pending = ""

        exit_code = await proc.wait()

    except asyncio.CancelledError:
        cancelled = True
        if proc is not None:
            with contextlib.suppress(Exception):
                await asyncio.shield(_terminate_process(proc))
    except Exception as exc:
        # Surface errors to the UI as a final line.
        msg = f"Execution error: {exc.__class__.__name__} {exc}"
        await emit_event(events.BashCommandOutputDeltaEvent(session_id=session_id, content=msg))
    finally:
        header = f"Ran {_format_inline_code(command)}"

        record_lines: list[str] = [header]
        if cancelled:
            record_lines.append("\n(command cancelled)")
        elif isinstance(exit_code, int) and exit_code != 0:
            record_lines.append(f"\nCommand exited with code {exit_code}")

        output_text = ""
        output_note_added = False
        try:
            if log_path.exists() and log_path.stat().st_size > BASH_MODE_SESSION_OUTPUT_MAX_BYTES:
                record_lines.append(
                    f"\n\n<system-reminder>Output truncated due to length. Full output saved to: {log_path} </system-reminder>"
                )
                output_note_added = True
            else:
                output_text = log_path.read_text("utf-8", errors="replace") if log_path.exists() else ""
        except OSError:
            output_text = ""

        if output_text.strip() == "":
            if not cancelled and not output_note_added:
                record_lines.append("\n(no output)")
                await emit_event(events.BashCommandOutputDeltaEvent(session_id=session_id, content="(no output)\n"))
        else:
            offloaded = offload_tool_output(output_text, _BashModeToolCall())
            record_lines.append("\n\n" + offloaded.output)

        # Always emit an end event so the renderer can finalize formatting.
        await emit_event(
            events.BashCommandEndEvent(
                session_id=session_id,
                exit_code=exit_code,
                cancelled=cancelled,
            )
        )
        session.append_history(
            [
                message.UserMessage(
                    parts=message.parts_from_text_and_images(
                        "".join(record_lines).rstrip(),
                        None,
                    )
                )
            ]
        )
