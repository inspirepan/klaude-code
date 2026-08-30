"""`klaude web` — open the browser session viewer hosted by the local server."""

from __future__ import annotations

import typer


def _resolve_web_url() -> str:
    """Ask the server (starting it if needed) for its web viewer URL."""

    from klaude_code.cli.uds_client import ServerNotRunningError, request_with_autostart
    from klaude_code.log import log

    try:
        status_code, body = request_with_autostart("GET", "/api/server/status", timeout=10.0)
    except ServerNotRunningError as exc:
        log((f"Error: could not reach the klaude server: {exc}", "red"))
        log(("Hint: run `klaude server run` in another terminal to see why", "yellow"))
        raise typer.Exit(1) from None
    if status_code != 200 or not isinstance(body, dict):
        log((f"Error: unexpected server response ({status_code}): {body}", "red"))
        raise typer.Exit(1)

    port = body.get("web_port")
    if not port:
        log(("Error: the klaude server has no web port", "red"))
        log(("It could not bind a loopback port for the viewer (all candidates busy).", "dim"))
        log(("Free a port near 8765, then: klaude server reload; see `klaude server logs`", "yellow"))
        raise typer.Exit(1)
    url = body.get("web_url")
    return str(url) if url else f"http://127.0.0.1:{port}"


def register_web_command(app: typer.Typer) -> None:
    @app.command("web")
    def web_command(  # pyright: ignore[reportUnusedFunction]
        no_open: bool = typer.Option(False, "--no-open", help="Print the URL without opening a browser"),
        print_url: bool = typer.Option(False, "--print-url", help="Print the URL only, for scripts"),
    ) -> None:
        """Open the web session viewer in a browser.

        The viewer is served by the local server on loopback and is read-only:
        it shows every session's trajectory live, but never sends input.
        """

        import webbrowser

        from klaude_code.log import log

        url = _resolve_web_url()
        if print_url:
            print(url)
            return
        log(f"klaude web viewer: {url}")
        if no_open:
            return
        if not webbrowser.open(url):
            log(("Could not open a browser; open the URL above manually", "yellow"))
