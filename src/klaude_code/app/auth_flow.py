"""Shared auth login/logout flows used by CLI and TUI commands."""

from __future__ import annotations

import datetime
import webbrowser

import typer

from klaude_code.log import log


def _configure_api_key(env_var: str) -> None:
    """Configure a specific API key."""
    import os

    from klaude_code.auth.env import get_auth_env, set_auth_env

    def _mask_secret(value: str, *, head: int = 8, tail: int = 6) -> str:
        token = value.strip()
        if not token:
            return "***"
        if len(token) <= head + tail:
            if len(token) <= 4:
                return "***"
            return f"{token[:2]}…{token[-2:]}"
        return f"{token[:head]}…{token[-tail:]}"

    current_value = os.environ.get(env_var) or get_auth_env(env_var)
    if current_value:
        masked = _mask_secret(current_value)
        log(f"Current {env_var}: {masked}")
        if not typer.confirm("Do you want to update it?"):
            return

    api_key = typer.prompt(f"Enter {env_var}", hide_input=True)
    if not api_key.strip():
        log(("Error: API key cannot be empty", "red"))
        raise typer.Exit(1)

    set_auth_env(env_var, api_key.strip())
    log((f"{env_var} saved successfully!", "green"))


def execute_login(provider: str) -> None:
    """Login to an OAuth provider or configure an API key provider."""
    match provider.lower():
        case "codex":
            from klaude_code.auth.codex.oauth import CodexOAuth
            from klaude_code.auth.codex.token_manager import CodexTokenManager

            token_manager = CodexTokenManager()

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
        case "copilot":
            from klaude_code.auth.copilot.oauth import CopilotOAuth
            from klaude_code.auth.copilot.token_manager import CopilotTokenManager

            token_manager = CopilotTokenManager()

            if token_manager.is_logged_in():
                state = token_manager.get_state()
                if state and not state.is_expired():
                    log(("You are already logged in to Copilot.", "green"))
                    domain = state.enterprise_domain or "github.com"
                    expires_dt = datetime.datetime.fromtimestamp(state.expires_at, tz=datetime.UTC)
                    log(f"  Domain: {domain}")
                    log(f"  Expires: {expires_dt.strftime('%Y-%m-%d %H:%M:%S UTC')}")
                    if not typer.confirm("Do you want to re-login?"):
                        return

            enterprise_input = typer.prompt(
                "GitHub Enterprise URL/domain (leave empty for github.com)",
                default="",
                show_default=False,
            )
            log("Starting GitHub Copilot OAuth device flow…")

            try:
                oauth = CopilotOAuth(token_manager)

                def _on_auth(url: str, code: str) -> None:
                    log(f"Open this URL in your browser: {url}")
                    log(f"Enter this code: {code}")
                    webbrowser.open(url)

                state = oauth.login(
                    enterprise_input=enterprise_input,
                    on_auth=_on_auth,
                    on_progress=lambda msg: log(msg),
                )
                log(("Login successful!", "green"))
                domain = state.enterprise_domain or "github.com"
                expires_dt = datetime.datetime.fromtimestamp(state.expires_at, tz=datetime.UTC)
                log(f"  Domain: {domain}")
                log(f"  Expires: {expires_dt.strftime('%Y-%m-%d %H:%M:%S UTC')}")
            except Exception as e:
                log((f"Login failed: {e}", "red"))
                raise typer.Exit(1) from None
        case _:
            from klaude_code.config.builtin_config import SUPPORTED_API_KEYS

            env_var: str | None = None
            provider_lower = provider.lower()
            provider_upper = provider.upper()
            for key_info in SUPPORTED_API_KEYS:
                name_lower = key_info.name.lower()
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


def execute_logout(provider: str) -> None:
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
        case "copilot":
            from klaude_code.auth.copilot.token_manager import CopilotTokenManager

            token_manager = CopilotTokenManager()

            if not token_manager.is_logged_in():
                log("You are not logged in to Copilot.")
                return

            if typer.confirm("Are you sure you want to logout from Copilot?"):
                token_manager.delete()
                log(("Logged out from Copilot.", "green"))
        case _:
            log((f"Error: Unknown provider '{provider}'. Supported: codex, claude, copilot", "red"))
            raise typer.Exit(1)
