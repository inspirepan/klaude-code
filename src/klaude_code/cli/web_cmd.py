from __future__ import annotations

import asyncio
import threading

import typer

from klaude_code.log import DebugType, log, log_debug


def register_web_commands(app: typer.Typer) -> None:
    @app.command("web")
    def web_command(  # pyright: ignore[reportUnusedFunction]
        host: str = typer.Option("127.0.0.1", "--host", help="Host to bind web server"),
        port: int = typer.Option(8765, "--port", help="Port to bind web server"),
        no_open: bool = typer.Option(False, "--no-open", help="Do not open browser automatically"),
        debug: bool = typer.Option(False, "--debug", help="Enable debug logs for web server"),
    ) -> None:
        try:
            from klaude_code.web.server import start_web_server
        except ModuleNotFoundError as exc:
            if exc.name in {"fastapi", "uvicorn"}:
                log(
                    (
                        "Web dependencies are missing. Install with: uv sync",
                        "red",
                    )
                )
                raise typer.Exit(2) from None
            raise

        try:
            log_debug(
                f"[web/cmd] asyncio.run start threads={[thread.name for thread in threading.enumerate()]}",
                debug_type=DebugType.EXECUTION,
            )
            asyncio.run(start_web_server(host=host, port=port, no_open=no_open, debug=debug))
            log_debug(
                f"[web/cmd] asyncio.run returned threads={[thread.name for thread in threading.enumerate()]}",
                debug_type=DebugType.EXECUTION,
            )
        except KeyboardInterrupt:
            log_debug(
                f"[web/cmd] KeyboardInterrupt exit threads={[thread.name for thread in threading.enumerate()]}",
                debug_type=DebugType.EXECUTION,
            )
            raise typer.Exit(130) from None
