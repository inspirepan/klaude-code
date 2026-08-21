"""Thin UDS HTTP client for CLI commands that talk to the local klaude server.

Import-light on purpose: headless subcommands run in a fresh process per
invocation, so heavy imports (httpx, server stack) stay inside functions.
"""

from __future__ import annotations

import functools
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from klaude_code.protocol.env_sync import ENV_SYNC_HEADER, encode_env_header
from klaude_code.protocol.version import is_protocol_compatible


class ServerNotRunningError(RuntimeError):
    pass


STALE_SERVER_HINT = (
    "klaude server is running stale code or an incompatible protocol; "
    "finish or kill running sessions, then: klaude server reload --force"
)
_RELOAD_WAIT_TIMEOUT = 30.0

# The handshake runs once per process; thin-client commands issue several
# requests and the check is only meaningful on the first contact.
_handshake_done = False


@functools.cache
def _client_env_header() -> str | None:
    """Return the env-sync header, or None when nothing referenced is set.

    The server is a long-lived daemon; its ``os.environ`` is frozen at launch
    and ``reload`` re-execs with that same env. Each request therefore carries
    the referenced variables from this process's env so the server merges them
    in before answering, keeping credential availability in step with the
    terminal that issued the command. Computed once per process: the CLI's env
    never changes and the merged config is cached.
    """
    try:
        from klaude_code.config import load_config

        values = load_config().referenced_env_values()
    except Exception:
        # Never let an env-header failure break the actual request.
        return None
    return encode_env_header(values) if values else None


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
    headers = None
    env_header = _client_env_header()
    if env_header is not None:
        headers = {ENV_SYNC_HEADER: env_header}
    try:
        with httpx.Client(transport=transport, base_url="http://klaude", timeout=timeout, headers=headers) as client:
            response = client.request(method, path, json=json_body, params=params)
    except httpx.TransportError as exc:
        raise ServerNotRunningError(str(socket_path)) from exc
    return response.status_code, response.json()


def _spawn_server_detached() -> None:
    argv0 = Path(sys.argv[0])
    if argv0.exists() and os.access(argv0, os.X_OK):
        command = [str(argv0.resolve()), "server", "run"]
    else:
        launcher = "from klaude_code.cli.main import app; app()"
        command = [sys.executable, "-c", launcher, "server", "run"]
    # The daemon must not inherit this client's CWD: it outlives the client,
    # serves sessions from many directories, and would otherwise pin whatever
    # directory the first `klaude` invocation happened to run in.
    subprocess.Popen(
        command,
        cwd=str(Path.home()),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def _warn(message: str) -> None:
    print(f"warning: {message}", file=sys.stderr)


def _local_code_fingerprint() -> str:
    from klaude_code.update import get_code_fingerprint

    return get_code_fingerprint()


def _server_matches(status_body: dict[str, Any], *, local_fingerprint: str) -> bool:
    return is_protocol_compatible(status_body.get("protocol_version")) and (
        status_body.get("code_fingerprint") == local_fingerprint
    )


def verify_server_code(status_body: dict[str, Any]) -> None:
    """Compatibility handshake: reload an idle stale server, warn on a busy one.

    A server started from older code produces confusing artifacts (stuck
    loading, ghost sessions), so every CLI entry compares the protocol and
    code fingerprint on first contact. Runs once per process; never raises on
    mismatch.
    """

    global _handshake_done
    if _handshake_done:
        return
    _handshake_done = True

    local_fingerprint = _local_code_fingerprint()
    if _server_matches(status_body, local_fingerprint=local_fingerprint):
        return

    sessions = status_body.get("sessions") or {}
    busy = any(int(sessions.get(key) or 0) > 0 for key in ("running", "waiting_input", "queued"))
    if busy:
        _warn(STALE_SERVER_HINT)
        return

    try:
        status, _body = request("POST", "/api/server/reload", json_body={"force": False}, timeout=10.0)
    except ServerNotRunningError:
        return  # Server went away; the autostart path brings up current code.
    if status == 409:
        # A session slipped in between the status check and the reload.
        _warn(STALE_SERVER_HINT)
        return
    if status != 200:
        _warn(f"klaude server auto-reload failed (HTTP {status}); it may be running stale code")
        return
    _wait_for_reloaded_server(local_fingerprint=local_fingerprint)


def _wait_for_reloaded_server(*, local_fingerprint: str) -> None:
    """Block until the reloaded server answers with matching code.

    Reload re-execs the server process in place (same pid), so the only
    reliable restart signal is the fingerprint itself. Old-process answers
    during the drain simply do not match and keep the loop polling. On
    timeout, warn and continue: the follow-up request either works or hits
    the autostart path.
    """

    deadline = time.monotonic() + _RELOAD_WAIT_TIMEOUT
    while time.monotonic() < deadline:
        time.sleep(0.25)
        try:
            status, body = request("GET", "/api/server/status", timeout=3.0)
        except ServerNotRunningError:
            continue  # Socket is down while the server re-execs.
        if status == 200 and isinstance(body, dict) and _server_matches(body, local_fingerprint=local_fingerprint):
            return
    _warn("klaude server did not come back on current code after reload; check `klaude server status`")


def ensure_server_running(*, startup_timeout: float = 20.0) -> None:
    """Auto-start the server when it is not reachable, then wait until it is.

    A reachable server also gets the version handshake (see
    ``verify_server_code``); a freshly spawned one runs this executable's
    code, so no check is needed.
    """

    global _handshake_done
    try:
        status, body = request("GET", "/api/server/status", timeout=3.0)
        if status == 200:
            if isinstance(body, dict):
                verify_server_code(body)
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
            _handshake_done = True
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
    if not _handshake_done:
        ensure_server_running()
    try:
        return request(method, path, json_body=json_body, params=params, timeout=timeout)
    except ServerNotRunningError:
        ensure_server_running()
        return request(method, path, json_body=json_body, params=params, timeout=timeout)
