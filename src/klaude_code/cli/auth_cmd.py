"""Authentication commands for CLI."""

import datetime

import typer

from klaude_code.trace import log


def login_command(
    provider: str = typer.Argument("codex", help="Provider to login (codex)"),
) -> None:
    """Login to a provider using OAuth."""
    if provider.lower() != "codex":
        log((f"Error: Unknown provider '{provider}'. Currently only 'codex' is supported.", "red"))
        raise typer.Exit(1)

    from klaude_code.auth.codex.oauth import CodexOAuth
    from klaude_code.auth.codex.token_manager import CodexTokenManager

    token_manager = CodexTokenManager()

    # Check if already logged in
    if token_manager.is_logged_in():
        state = token_manager.get_state()
        if state and not state.is_expired():
            log(("You are already logged in to Codex.", "green"))
            log(f"  Account ID: {state.account_id[:8]}...")
            expires_dt = datetime.datetime.fromtimestamp(state.expires_at, tz=datetime.UTC)
            log(f"  Expires: {expires_dt.strftime('%Y-%m-%d %H:%M:%S UTC')}")
            if not typer.confirm("Do you want to re-login?"):
                return

    log("Starting Codex OAuth login flow...")
    log("A browser window will open for authentication.")

    try:
        oauth = CodexOAuth(token_manager)
        state = oauth.login()
        log(("Login successful!", "green"))
        log(f"  Account ID: {state.account_id[:8]}...")
        expires_dt = datetime.datetime.fromtimestamp(state.expires_at, tz=datetime.UTC)
        log(f"  Expires: {expires_dt.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    except Exception as e:
        log((f"Login failed: {e}", "red"))
        raise typer.Exit(1) from None


def logout_command(
    provider: str = typer.Argument("codex", help="Provider to logout (codex)"),
) -> None:
    """Logout from a provider."""
    if provider.lower() != "codex":
        log((f"Error: Unknown provider '{provider}'. Currently only 'codex' is supported.", "red"))
        raise typer.Exit(1)

    from klaude_code.auth.codex.token_manager import CodexTokenManager

    token_manager = CodexTokenManager()

    if not token_manager.is_logged_in():
        log("You are not logged in to Codex.")
        return

    if typer.confirm("Are you sure you want to logout from Codex?"):
        token_manager.delete()
        log(("Logged out from Codex.", "green"))


def register_auth_commands(app: typer.Typer) -> None:
    """Register auth commands to the given Typer app."""
    app.command("login")(login_command)
    app.command("logout")(logout_command)
