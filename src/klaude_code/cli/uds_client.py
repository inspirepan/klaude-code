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
STALE_SERVER_PENDING_HINT = (
    "klaude server is running older code; it restarts once its active sessions finish "
    "(interrupt them with: klaude server reload --force)"
)
_RELOAD_WAIT_TIMEOUT = 30.0
# The TUI attach path spawns the server concurrently; the upgrade request
# waits this long for it to answer before giving up silently.
_UPGRADE_REQUEST_TIMEOUT = 30.0

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


def _spawn_server_detached() -> subprocess.Popen[bytes]:
    from klaude_code.server.startup_log import STARTUP_LOG_ENV, server_startup_log_path

    argv0 = Path(sys.argv[0])
    if argv0.exists() and os.access(argv0, os.X_OK):
        command = [str(argv0.resolve()), "server", "run"]
    else:
        launcher = "from klaude_code.cli.main import app; app()"
        command = [sys.executable, "-c", launcher, "server", "run"]
    # The daemon must not inherit this client's CWD: it outlives the client,
    # serves sessions from many directories, and would otherwise pin whatever
    # directory the first `klaude` invocation happened to run in.
    # Startup output lands in a log so a boot failure can be reported instead
    # of timing out; the server itself redirects to it again on every boot.
    log_path = server_startup_log_path()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("wb") as log_file:
        return subprocess.Popen(
            command,
            cwd=str(Path.home()),
            env={**os.environ, STARTUP_LOG_ENV: str(log_path)},
            stdin=subprocess.DEVNULL,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )


def _startup_failure(reason: str) -> ServerNotRunningError:
    from klaude_code.server.startup_log import read_startup_log_tail, server_startup_log_path

    tail = read_startup_log_tail()
    if not tail:
        return ServerNotRunningError(f"{reason} (no output in {server_startup_log_path()})")
    indented = "\n".join(f"  {line}" for line in tail.splitlines())
    return ServerNotRunningError(f"{reason}; server output:\n{indented}")


def _process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


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
    """Compatibility handshake: ask a stale server to reload at its next idle boundary.

    A server started from older code produces confusing artifacts (stuck
    loading, ghost sessions), so every CLI entry compares the protocol and
    code fingerprint on first contact. The server owns the timing: an idle
    one re-execs right away and this call waits for it; a busy one keeps the
    reload pending and fires it when its sessions finish. Runs once per
    process; never raises on mismatch.
    """

    global _handshake_done
    if _handshake_done:
        return
    _handshake_done = True

    local_fingerprint = _local_code_fingerprint()
    if _server_matches(status_body, local_fingerprint=local_fingerprint):
        return

    try:
        status, body = request("POST", "/api/server/reload", json_body={"force": False, "when": "idle"}, timeout=10.0)
    except ServerNotRunningError:
        return  # Server went away; the autostart path brings up current code.
    if status == 409:
        # Older server without idle scheduling: it only knows now-or-refuse.
        _warn(STALE_SERVER_HINT)
        return
    if status != 200 or not isinstance(body, dict):
        _warn(f"klaude server auto-reload failed (HTTP {status}); it may be running stale code")
        return
    if body.get("sessions"):
        _warn(STALE_SERVER_PENDING_HINT)
        return
    pid = body.get("pid")
    outcome = wait_for_reloaded_server(local_fingerprint=local_fingerprint, pid=pid if isinstance(pid, int) else None)
    if outcome == "timeout":
        _warn("klaude server did not come back on current code after reload; check `klaude server status`")
    # "exited": the follow-up request hits the autostart path, which reports why.


def wait_for_reloaded_server(
    *, local_fingerprint: str | None, pid: int | None = None, timeout: float | None = None
) -> str:
    """Block until the reloaded server answers with matching code.

    Reload re-execs the server process in place (same pid), so the only
    reliable restart signal is the fingerprint itself. Old-process answers
    during the drain simply do not match and keep the loop polling. With
    ``local_fingerprint`` None any compatible server that answers after the
    socket went down counts. Returns "ok", "exited" (the re-exec'd process
    died, e.g. on a config error) or "timeout".
    """

    deadline = time.monotonic() + (_RELOAD_WAIT_TIMEOUT if timeout is None else timeout)
    saw_down = False
    while time.monotonic() < deadline:
        time.sleep(0.25)
        try:
            status, body = request("GET", "/api/server/status", timeout=3.0)
        except ServerNotRunningError:
            # Socket is down while the server re-execs; a gone pid means the
            # new code failed to boot, so waiting longer cannot help.
            saw_down = True
            if pid is not None and not _process_alive(pid):
                return "exited"
            continue
        if status != 200 or not isinstance(body, dict):
            continue
        if local_fingerprint is not None:
            if _server_matches(body, local_fingerprint=local_fingerprint):
                return "ok"
        elif saw_down and is_protocol_compatible(body.get("protocol_version")):
            return "ok"
    return "timeout"


def request_server_upgrade(*, check: bool = False, timeout: float = _UPGRADE_REQUEST_TIMEOUT) -> dict[str, Any] | None:
    """Ask the server to install the latest code at its next idle boundary.

    Retries while the server is still booting. Returns the server's upgrade
    status, or None when no server answered in time or it predates the
    endpoint.
    """

    deadline = time.monotonic() + timeout
    while True:
        try:
            status, body = request("POST", "/api/server/upgrade", json_body={"check": check}, timeout=10.0)
            break
        except ServerNotRunningError:
            if time.monotonic() >= deadline:
                return None
            time.sleep(0.5)
    if status != 200 or not isinstance(body, dict):
        return None
    return body


def describe_upgrade_status(status: dict[str, Any]) -> str | None:
    """One user-facing line for a server upgrade status, or None when idle."""

    phase = status.get("phase")
    action = "install the update and restart" if status.get("action") == "upgrade" else "restart"
    if phase == "pending":
        active = status.get("active_sessions") or []
        if active:
            noun = "session" if len(active) == 1 else "sessions"
            return f"klaude server will {action} once {len(active)} active {noun} finish (/reload to check)."
        return f"klaude server is about to {action}; this client reconnects automatically."
    if phase == "installing":
        return "klaude server is installing the update and restarts when done."
    if phase == "reloading":
        return "klaude server is restarting on the updated code."
    if phase == "failed":
        message = status.get("message") or "unknown error"
        return f"klaude upgrade failed: {message}"
    return None


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

    process = _spawn_server_detached()
    deadline = time.monotonic() + startup_timeout
    while time.monotonic() < deadline:
        time.sleep(0.25)
        try:
            status, _ = request("GET", "/api/server/status", timeout=3.0)
        except ServerNotRunningError:
            returncode = process.poll()
            if returncode is None:
                continue
            if _lost_singleton_race():
                # Another client's spawn won the lock; wait for that server.
                continue
            raise _startup_failure(f"klaude server exited during startup (code {returncode})") from None
        if status == 200:
            _handshake_done = True
            return
    raise _startup_failure("klaude server did not start in time")


def _lost_singleton_race() -> bool:
    from klaude_code.server.startup_log import read_startup_log_tail

    return "already running" in read_startup_log_tail()


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
