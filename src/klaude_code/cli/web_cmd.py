"""Start a read-only history viewer on demand."""

import typer


def register_web_command(app: typer.Typer) -> None:
    @app.command("web")
    def web_command(
        port: int = typer.Option(8765, "--port", help="Loopback HTTP port"),
        no_open: bool = typer.Option(False, "--no-open", help="Do not open a browser"),
    ) -> None:
        import webbrowser

        import uvicorn

        from klaude_code.server.read_only import create_read_only_app

        url = f"http://127.0.0.1:{port}"
        typer.echo(f"Klaude history: {url}")
        if not no_open:
            webbrowser.open(url)
        uvicorn.run(create_read_only_app(web_port=port), host="127.0.0.1", port=port, log_level="warning")
