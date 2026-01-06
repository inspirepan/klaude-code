"""Authentication commands for CLI."""

import datetime
import webbrowser

import typer

from klaude_code.log import log
from klaude_code.tui.terminal.selector import DEFAULT_PICKER_STYLE, SelectItem, select_one


def _select_provider() -> str | None:
    """Display provider selection menu and return selected provider."""
    items: list[SelectItem[str]] = [
        SelectItem(title=[("class:text", "Claude Max/Pro Subscription\n")], value="claude", search_text="claude"),
        SelectItem(title=[("class:text", "ChatGPT Codex Subscription\n")], value="codex", search_text="codex"),
    ]
    return select_one(
        message="Select provider to login:",
        items=items,
        pointer="→",
        style=DEFAULT_PICKER_STYLE,
        use_search_filter=False,
    )


def login_command(
    provider: str | None = typer.Argument(None, help="Provider to login (codex|claude)"),
) -> None:
    """Login to a provider using OAuth."""
    if provider is None:
        provider = _select_provider()
        if provider is None:
            return

    match provider.lower():
        case "codex":
            from klaude_code.auth.codex.oauth import CodexOAuth
            from klaude_code.auth.codex.token_manager import CodexTokenManager

            token_manager = CodexTokenManager()

            # Check if already logged in
            if token_manager.is_logged_in():
                state = token_manager.get_state()
                if state and not state.is_expired():
                    log(("You are already logged in to Codex.", "green"))
                    log(f"  Account ID: {state.account_id[:8]}…")
                    expires_dt = datetime.datetime.fromtimestamp(state.expires_at, tz=datetime.UTC)
                    log(f"  Expires: {expires_dt.strftime('%Y-%m-%d %H:%M:%S UTC')}")
                    if not typer.confirm("Do you want to re-login?"):
                        return

            log("Starting Codex OAuth login flow…")
            log("A browser window will open for authentication.")

            try:
                oauth = CodexOAuth(token_manager)
                state = oauth.login()
                log(("Login successful!", "green"))
                log(f"  Account ID: {state.account_id[:8]}…")
                expires_dt = datetime.datetime.fromtimestamp(state.expires_at, tz=datetime.UTC)
                log(f"  Expires: {expires_dt.strftime('%Y-%m-%d %H:%M:%S UTC')}")
            except Exception as e:
                log((f"Login failed: {e}", "red"))
                raise typer.Exit(1) from None
        case "claude":
            from klaude_code.auth.claude.oauth import ClaudeOAuth
            from klaude_code.auth.claude.token_manager import ClaudeTokenManager

            token_manager = ClaudeTokenManager()

            if token_manager.is_logged_in():
                state = token_manager.get_state()
                if state and not state.is_expired():
                    log(("You are already logged in to Claude.", "green"))
                    expires_dt = datetime.datetime.fromtimestamp(state.expires_at, tz=datetime.UTC)
                    log(f"  Expires: {expires_dt.strftime('%Y-%m-%d %H:%M:%S UTC')}")
                    if not typer.confirm("Do you want to re-login?"):
                        return

            log("Starting Claude OAuth login flow…")
            log("A browser window will open for authentication.")
            log("After login, paste the authorization code in the terminal.")

            try:
                oauth = ClaudeOAuth(token_manager)
                state = oauth.login(
                    on_auth_url=lambda url: (webbrowser.open(url), None)[1],
                    on_prompt_code=lambda: typer.prompt(
                        "Paste the authorization code (format: code#state)",
                        prompt_suffix=": ",
                    ),
                )
                log(("Login successful!", "green"))
                expires_dt = datetime.datetime.fromtimestamp(state.expires_at, tz=datetime.UTC)
                log(f"  Expires: {expires_dt.strftime('%Y-%m-%d %H:%M:%S UTC')}")
            except Exception as e:
                log((f"Login failed: {e}", "red"))
                raise typer.Exit(1) from None
        case _:
            log((f"Error: Unknown provider '{provider}'. Supported: codex, claude", "red"))
            raise typer.Exit(1)


def logout_command(
    provider: str = typer.Argument("codex", help="Provider to logout (codex|claude)"),
) -> None:
    """Logout from a provider."""
    match provider.lower():
        case "codex":
            from klaude_code.auth.codex.token_manager import CodexTokenManager

            token_manager = CodexTokenManager()

            if not token_manager.is_logged_in():
                log("You are not logged in to Codex.")
                return

            if typer.confirm("Are you sure you want to logout from Codex?"):
                token_manager.delete()
                log(("Logged out from Codex.", "green"))
        case "claude":
            from klaude_code.auth.claude.token_manager import ClaudeTokenManager

            token_manager = ClaudeTokenManager()

            if not token_manager.is_logged_in():
                log("You are not logged in to Claude.")
                return

            if typer.confirm("Are you sure you want to logout from Claude?"):
                token_manager.delete()
                log(("Logged out from Claude.", "green"))
        case _:
            log((f"Error: Unknown provider '{provider}'. Supported: codex, claude", "red"))
            raise typer.Exit(1)


def register_auth_commands(app: typer.Typer) -> None:
    """Register auth commands to the given Typer app."""
    app.command("login")(login_command)
    app.command("logout")(logout_command)
