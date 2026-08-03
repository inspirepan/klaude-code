"""`klaude server` subcommands: manage the local klaude server over its Unix socket."""

from __future__ import annotations

import asyncio
import os
import sys
import time
from collections import deque
from pathlib import Path
from typing import Any, NoReturn

import typer

from klaude_code.log import log

server_app = typer.Typer(
    help="Manage the local klaude server",
    no_args_is_help=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)


def register_server_commands(app: typer.Typer) -> None:
    app.add_typer(server_app, name="server")


# -- UDS HTTP client (thin; heavy imports stay lazy) --


class ServerNotRunningError(RuntimeError):
    pass


def _request(method: str, path: str, json_body: dict[str, Any] | None = None, timeout: float = 10.0) -> Any:
    """Send one HTTP request over the server's Unix socket and return (status, body)."""

    import httpx

    from klaude_code.server.paths import server_socket_path

    socket_path = server_socket_path()
    if not socket_path.exists():
        raise ServerNotRunningError(str(socket_path))
    transport = httpx.HTTPTransport(uds=str(socket_path))
    try:
        with httpx.Client(transport=transport, base_url="http://klaude", timeout=timeout) as client:
            response = client.request(method, path, json=json_body)
    except httpx.TransportError as exc:
        raise ServerNotRunningError(str(socket_path)) from exc
    return response.status_code, response.json()


def _print_not_running(socket_path_hint: str) -> None:
    log(("klaude server is not running", "yellow"))
    log((f"  socket: {socket_path_hint}", "dim"))
    log(("Start it with: klaude server run", "dim"))


def _format_uptime(seconds: float) -> str:
    total = int(seconds)
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes}m {secs}s"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


def _reexec_self() -> NoReturn:
    """Replace this process with a fresh one using the original arguments."""

    sys.stdout.flush()
    sys.stderr.flush()
    argv0 = Path(sys.argv[0])
    if argv0.exists() and os.access(argv0, os.X_OK):
        os.execv(str(argv0), sys.argv)
    # Fallback: argv[0] is not directly executable; run it through the interpreter.
    os.execv(sys.executable, [sys.executable, *sys.argv])


# -- commands --


@server_app.command("run")
def run_command(
    debug: bool = typer.Option(False, "--debug", help="Enable debug logging"),
) -> None:
    """Run the server in the foreground (debugging)."""

    from klaude_code.server.server import ServerAlreadyRunningError, start_server

    try:
        reload_requested = asyncio.run(start_server(debug=debug))
    except ServerAlreadyRunningError as exc:
        log((str(exc), "yellow"))
        raise typer.Exit(1) from None
    except KeyboardInterrupt:
        raise typer.Exit(130) from None
    if reload_requested:
        log(("Reloading klaude server...", "green"))
        _reexec_self()


@server_app.command("status")
def status_command() -> None:
    """Show pid, socket path, uptime, version, and session counts."""

    from klaude_code.server.paths import server_socket_path

    try:
        status_code, body = _request("GET", "/api/server/status")
    except ServerNotRunningError as exc:
        _print_not_running(str(exc))
        raise typer.Exit(1) from None
    if status_code != 200:
        log((f"Unexpected server response ({status_code}): {body}", "red"))
        raise typer.Exit(1)

    sessions = body.get("sessions", {})
    log("klaude server is running")
    log(f"  pid:      {body.get('pid')}")
    log(f"  socket:   {server_socket_path()}")
    log(f"  uptime:   {_format_uptime(float(body.get('uptime_seconds', 0)))}")
    log(f"  version:  {body.get('version')}")
    log(
        f"  sessions: {sessions.get('loaded', 0)} loaded, "
        f"{sessions.get('running', 0)} running, "
        f"{sessions.get('waiting_input', 0)} waiting for input"
    )


@server_app.command("stop")
def stop_command() -> None:
    """Gracefully stop the server (interrupts running agents)."""

    try:
        status_code, body = _request("POST", "/api/server/stop")
    except ServerNotRunningError as exc:
        _print_not_running(str(exc))
        return
    if status_code != 200:
        log((f"Unexpected server response ({status_code}): {body}", "red"))
        raise typer.Exit(1)
    log((f"klaude server is stopping (pid {body.get('pid')})", "green"))


@server_app.command("reload")
def reload_command(
    force: bool = typer.Option(False, "--force", help="Interrupt running sessions before reloading"),
) -> None:
    """Gracefully restart the server on the current code.

    Refuses when sessions are running unless --force is given. Idle sessions
    are unaffected: they live on disk and rehydrate on demand.
    """

    try:
        status_code, body = _request("POST", "/api/server/reload", json_body={"force": force})
    except ServerNotRunningError as exc:
        _print_not_running(str(exc))
        raise typer.Exit(1) from None
    if status_code == 409:
        detail = body.get("detail", {}) if isinstance(body, dict) else {}
        sessions = detail.get("sessions", []) if isinstance(detail, dict) else []
        log(("Refusing to reload: sessions are still active", "yellow"))
        for item in sessions:
            log((f"  {item.get('session_id')}  {item.get('state')}", "dim"))
        log(("Use --force to interrupt them (sessions stay resumable)", "dim"))
        raise typer.Exit(1)
    if status_code != 200:
        log((f"Unexpected server response ({status_code}): {body}", "red"))
        raise typer.Exit(1)
    log((f"klaude server is reloading (pid {body.get('pid')})", "green"))


@server_app.command("logs")
def logs_command(
    lines: int = typer.Option(100, "--lines", "-n", help="Number of trailing lines to print"),
    follow: bool = typer.Option(False, "--follow", "-f", help="Keep printing new log lines"),
) -> None:
    """Tail the server log file."""

    from klaude_code.server.paths import server_log_file_path

    log_path = server_log_file_path()
    if not log_path.exists():
        log((f"No server log file at {log_path}", "yellow"))
        raise typer.Exit(1)

    with log_path.open("r", encoding="utf-8", errors="replace") as f:
        for line in deque(f, maxlen=lines):
            print(line, end="")
        if not follow:
            return
        try:
            while True:
                chunk = f.readline()
                if chunk:
                    print(chunk, end="")
                else:
                    time.sleep(0.5)
        except KeyboardInterrupt:
            return
