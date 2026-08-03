"""Filesystem locations shared by the server and its CLI clients.

Import-light on purpose: thin clients (``klaude server status`` etc.) load
this module on every invocation.
"""

from __future__ import annotations

from pathlib import Path

from klaude_code.const import DEFAULT_DEBUG_LOG_DIR


def server_run_dir(home_dir: Path | None = None) -> Path:
    return (home_dir or Path.home()) / ".klaude" / "run"


def server_socket_path(home_dir: Path | None = None) -> Path:
    return server_run_dir(home_dir) / "server.sock"


def server_lock_path(home_dir: Path | None = None) -> Path:
    return server_run_dir(home_dir) / "server.lock"


def server_log_file_path() -> Path:
    return DEFAULT_DEBUG_LOG_DIR / "server.log"
