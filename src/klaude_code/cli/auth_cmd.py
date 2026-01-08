"""Authentication commands for CLI."""

import datetime
import webbrowser

import typer

from klaude_code.log import log
from klaude_code.tui.terminal.selector import DEFAULT_PICKER_STYLE, SelectItem, select_one


def _select_provider() -> str | None:
    """Display provider selection menu and return selected provider."""
    from klaude_code.config.builtin_config import SUPPORTED_API_KEYS

    items: list[SelectItem[str]] = [
        SelectItem(
            title=[("", "Claude Max/Pro Subscription "), ("ansibrightblack", "[OAuth]\n")],
            value="claude",
            search_text="claude",
        ),
        SelectItem(
            title=[("", "ChatGPT Codex Subscription "), ("ansibrightblack", "[OAuth]\n")],
            value="codex",
            search_text="codex",
        ),
        SelectItem(
            title=[("", "Google Antigravity "), ("ansibrightblack", "[OAuth]\n")],
            value="antigravity",
            search_text="antigravity",
        ),
    ]
    # Add API key options
    for key_info in SUPPORTED_API_KEYS:
        items.append(
            SelectItem(
                title=[("", f"{key_info.name} "), ("ansibrightblack", "[API key]\n")],
                value=key_info.env_var,
                search_text=key_info.env_var,
            )
        )

    return select_one(
        message="Select provider to login:",
        items=items,
        pointer="→",
        style=DEFAULT_PICKER_STYLE,
        use_search_filter=False,
    )


def _configure_api_key(env_var: str) -> None:
    """Configure a specific API key."""
    import os

    from klaude_code.auth.env import get_auth_env, set_auth_env

    # Check if already configured
    current_value = os.environ.get(env_var) or get_auth_env(env_var)
    if current_value:
        masked = current_value[:8] + "..." if len(current_value) > 8 else "***"
        log(f"Current {env_var}: {masked}")
        if not typer.confirm("Do you want to update it?"):
            return

    api_key = typer.prompt(f"Enter {env_var}", hide_input=True)
    if not api_key.strip():
        log(("Error: API key cannot be empty", "red"))
        raise typer.Exit(1)

    set_auth_env(env_var, api_key.strip())
    log((f"{env_var} saved successfully!", "green"))


def _build_provider_help() -> str:
    from klaude_code.config.builtin_config import SUPPORTED_API_KEYS

    # Use first word of name for brevity (e.g., "google" instead of "google gemini")
    names = ["codex", "claude", "antigravity"] + [k.name.split()[0].lower() for k in SUPPORTED_API_KEYS]
    return f"Provider name ({', '.join(names)})"


def login_command(
    provider: str | None = typer.Argument(None, help=_build_provider_help()),
) -> None:
    """Login to a provider or configure API keys."""
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
        case "antigravity":
            from klaude_code.auth.antigravity.oauth import AntigravityOAuth
            from klaude_code.auth.antigravity.token_manager import AntigravityTokenManager

            token_manager = AntigravityTokenManager()

            if token_manager.is_logged_in():
                state = token_manager.get_state()
                if state and not state.is_expired():
                    log(("You are already logged in to Antigravity.", "green"))
                    if state.email:
                        log(f"  Email: {state.email}")
                    log(f"  Project ID: {state.project_id}")
                    expires_dt = datetime.datetime.fromtimestamp(state.expires_at, tz=datetime.UTC)
                    log(f"  Expires: {expires_dt.strftime('%Y-%m-%d %H:%M:%S UTC')}")
                    if not typer.confirm("Do you want to re-login?"):
                        return

            log("Starting Antigravity OAuth login flow...")
            log("A browser window will open for authentication.")

            try:
                oauth = AntigravityOAuth(token_manager)
                state = oauth.login()
                log(("Login successful!", "green"))
                if state.email:
                    log(f"  Email: {state.email}")
                log(f"  Project ID: {state.project_id}")
                expires_dt = datetime.datetime.fromtimestamp(state.expires_at, tz=datetime.UTC)
                log(f"  Expires: {expires_dt.strftime('%Y-%m-%d %H:%M:%S UTC')}")
            except Exception as e:
                log((f"Login failed: {e}", "red"))
                raise typer.Exit(1) from None
        case _:
            from klaude_code.config.builtin_config import SUPPORTED_API_KEYS

            # Match by env var (e.g., OPENAI_API_KEY) or name (e.g., openai, google)
            env_var: str | None = None
            provider_lower = provider.lower()
            provider_upper = provider.upper()
            for key_info in SUPPORTED_API_KEYS:
                name_lower = key_info.name.lower()
                # Exact match or starts with (for "google" -> "google gemini")
                if key_info.env_var == provider_upper or name_lower == provider_lower:
                    env_var = key_info.env_var
                    break
                if name_lower.startswith(provider_lower) or provider_lower in name_lower.split():
                    env_var = key_info.env_var
                    break

            if env_var:
                _configure_api_key(env_var)
            else:
                log((f"Error: Unknown provider '{provider}'", "red"))
                raise typer.Exit(1)


def logout_command(
    provider: str = typer.Argument("codex", help="Provider to logout (codex|claude|antigravity)"),
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
        case "antigravity":
            from klaude_code.auth.antigravity.token_manager import AntigravityTokenManager

            token_manager = AntigravityTokenManager()

            if not token_manager.is_logged_in():
                log("You are not logged in to Antigravity.")
                return

            if typer.confirm("Are you sure you want to logout from Antigravity?"):
                token_manager.delete()
                log(("Logged out from Antigravity.", "green"))
        case _:
            log((f"Error: Unknown provider '{provider}'. Supported: codex, claude, antigravity", "red"))
            raise typer.Exit(1)


def register_auth_commands(app: typer.Typer) -> None:
    """Register auth commands to the given Typer app."""
    auth_app = typer.Typer(help="Login/logout", invoke_without_command=True)

    @auth_app.callback()
    def auth_callback(ctx: typer.Context) -> None:  # pyright: ignore[reportUnusedFunction]
        """Authentication commands for managing provider logins."""
        if ctx.invoked_subcommand is None:
            typer.echo(ctx.get_help())

    auth_app.command("login")(login_command)
    auth_app.command("logout")(logout_command)
    app.add_typer(auth_app, name="auth")
