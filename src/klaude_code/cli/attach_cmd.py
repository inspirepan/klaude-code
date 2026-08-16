"""`klaude attach` — open the TUI on an existing session (replay + live)."""

from __future__ import annotations

import asyncio
import sys

import typer


def _resolve_attach_target(target: str) -> str:
    """Resolve a session id prefix or name via the server; exit 1 on failure."""
    from klaude_code.cli.uds_client import request_with_autostart

    status, body = request_with_autostart("GET", "/api/headless/sessions", params={"targets": target, "limit": 1})
    if status == 200:
        rows = body.get("sessions") or []
        if rows and isinstance(rows[0], dict) and rows[0].get("id"):
            return str(rows[0]["id"])
        typer.echo(f"error: session not found: {target}", err=True)
        raise typer.Exit(1)
    detail = body.get("detail") if isinstance(body, dict) else body
    typer.echo(f"error: {detail}", err=True)
    raise typer.Exit(1)


def run_attach_tui(session_id: str, *, peek: bool = False, debug: bool = False) -> None:
    """Shared entry: ensure server, then run the attach TUI (blocking)."""
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        from klaude_code.log import log

        log(("Error: interactive mode requires a TTY", "red"))
        raise typer.Exit(2)

    from klaude_code.cli.main import prepare_debug_logging
    from klaude_code.cli.uds_client import ensure_server_running
    from klaude_code.log import log
    from klaude_code.tui.runner import run_attach

    ensure_server_running()
    try:
        debug_enabled, log_path = prepare_debug_logging(debug)
    except Exception as exc:
        log((f"Error: failed to enable debug logging: {exc}", "red"))
        raise typer.Exit(1) from None
    del debug_enabled
    if log_path:
        from klaude_code.app.log_viewer import start_log_viewer

        log(f"Debug log: {log_path}")
        viewer_url = start_log_viewer(log_path)
        log(f"Log viewer: {viewer_url}")
    asyncio.run(run_attach(session_id, peek=peek))


def register_attach_command(app: typer.Typer) -> None:
    @app.command("attach")
    def attach_command(  # pyright: ignore[reportUnusedFunction]
        target: str | None = typer.Argument(None, metavar="[TARGET]"),
        peek: bool = typer.Option(False, "--peek", help="Read-only: follow without input"),
        debug: bool = typer.Option(False, "--debug", "-d", help="Enable debug logging"),
    ) -> None:
        """Open the TUI on a session: replay the conversation so far, then
        follow live. Multiple clients may attach to the same session and all
        may type; execution is serialized by the server. Detaching (exit,
        Ctrl+D, closing the terminal) never stops the agent.

        With no TARGET, opens the interactive session picker (same as -r).
        TARGET is a session id (unique prefix is enough) or a `run --name`.
        """
        if target is None:
            from klaude_code.tui.terminal.session_selector import select_session_sync

            selected = select_session_sync()
            if selected is None:
                raise typer.Exit(1)
            session_id = selected
        else:
            from klaude_code.cli.uds_client import ensure_server_running

            ensure_server_running()
            session_id = _resolve_attach_target(target)
        run_attach_tui(session_id, peek=peek, debug=debug)
