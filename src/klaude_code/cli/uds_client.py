"""Thin UDS HTTP client for CLI commands that talk to the local klaude server.

Import-light on purpose: headless subcommands run in a fresh process per
invocation, so heavy imports (httpx, server stack) stay inside functions.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


class ServerNotRunningError(RuntimeError):
    pass


def request(
    method: str,
    path: str,
    *,
    json_body: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
    timeout: float = 30.0,
) -> tuple[int, Any]:
    """Send one HTTP request over the server's Unix socket; return (status, body)."""

    import httpx

    from klaude_code.server.paths import server_socket_path

    socket_path = server_socket_path()
    if not socket_path.exists():
        raise ServerNotRunningError(str(socket_path))
    transport = httpx.HTTPTransport(uds=str(socket_path))
    try:
        with httpx.Client(transport=transport, base_url="http://klaude", timeout=timeout) as client:
            response = client.request(method, path, json=json_body, params=params)
    except httpx.TransportError as exc:
        raise ServerNotRunningError(str(socket_path)) from exc
    return response.status_code, response.json()


def _spawn_server_detached() -> None:
    argv0 = Path(sys.argv[0])
    if argv0.exists() and os.access(argv0, os.X_OK):
        command = [str(argv0), "server", "run"]
    else:
        launcher = "from klaude_code.cli.main import app; app()"
        command = [sys.executable, "-c", launcher, "server", "run"]
    subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def ensure_server_running(*, startup_timeout: float = 20.0) -> None:
    """Auto-start the server when it is not reachable, then wait until it is."""

    try:
        status, _ = request("GET", "/api/server/status", timeout=3.0)
        if status == 200:
            return
    except ServerNotRunningError:
        pass

    _spawn_server_detached()
    deadline = time.monotonic() + startup_timeout
    while time.monotonic() < deadline:
        time.sleep(0.25)
        try:
            status, _ = request("GET", "/api/server/status", timeout=3.0)
        except ServerNotRunningError:
            continue
        if status == 200:
            return
    raise ServerNotRunningError("klaude server did not start in time")


def request_with_autostart(
    method: str,
    path: str,
    *,
    json_body: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
    timeout: float = 30.0,
) -> tuple[int, Any]:
    try:
        return request(method, path, json_body=json_body, params=params, timeout=timeout)
    except ServerNotRunningError:
        ensure_server_running()
        return request(method, path, json_body=json_body, params=params, timeout=timeout)
