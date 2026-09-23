"""Capture a detached server's startup output so clients can report boot failures.

A detached server has no terminal: an error raised before it listens (bad
config, import failure) would otherwise vanish, and the client could only time
out. The spawner names a startup log through an env var; the server writes its
stdout/stderr there until it listens, then detaches so uvicorn's per-request
output does not grow the file (runtime logs live in the rotated server.log).

Import-light on purpose: thin clients load this on every autostart.
"""

from __future__ import annotations

import contextlib
import os
from pathlib import Path

STARTUP_LOG_ENV = "KLAUDE_SERVER_STARTUP_LOG"
_TAIL_LINES = 20


def server_startup_log_path(home_dir: Path | None = None) -> Path:
    return (home_dir or Path.home()) / ".klaude" / "run" / "server-start.log"


def redirect_output_to_startup_log() -> None:
    """Point fd 1/2 at the startup log named by the env var, truncating it.

    Runs on every boot, including a reload re-exec, whose inherited fds were
    already detached by the previous boot.
    """
    path = os.environ.get(STARTUP_LOG_ENV)
    if not path:
        return
    try:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    except OSError:
        return
    try:
        os.dup2(fd, 1)
        os.dup2(fd, 2)
    finally:
        os.close(fd)


def detach_output_from_startup_log() -> None:
    """Send fd 1/2 to /dev/null once the server listens."""
    if not os.environ.get(STARTUP_LOG_ENV):
        return
    try:
        fd = os.open(os.devnull, os.O_WRONLY)
    except OSError:
        return
    try:
        os.dup2(fd, 1)
        os.dup2(fd, 2)
    finally:
        os.close(fd)


def read_startup_log_tail(path: Path | None = None) -> str:
    target = path or server_startup_log_path()
    with contextlib.suppress(OSError):
        lines = target.read_text(encoding="utf-8", errors="replace").strip().splitlines()
        return "\n".join(lines[-_TAIL_LINES:])
    return ""
