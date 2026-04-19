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


def _configure_aws_bedrock() -> None:
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

    fields: list[tuple[str, str, bool]] = [
        ("AWS_BEDROCK_ACCESS_KEY_ID", "Enter AWS_BEDROCK_ACCESS_KEY_ID", False),
        ("AWS_BEDROCK_SECRET_ACCESS_KEY", "Enter AWS_BEDROCK_SECRET_ACCESS_KEY", True),
        ("AWS_BEDROCK_REGION", "Enter AWS_BEDROCK_REGION (e.g. us-east-1)", False),
    ]

    for env_var, prompt, is_secret in fields:
        current_value = os.environ.get(env_var) or get_auth_env(env_var)
        if current_value:
            display = _mask_secret(current_value) if is_secret else current_value
            log(f"Current {env_var}: {display}")
            if not typer.confirm("Do you want to update it?"):
                continue

        value = typer.prompt(prompt, hide_input=is_secret)
        if not value.strip():
            log((f"Error: {env_var} cannot be empty", "red"))
            raise typer.Exit(1)

        set_auth_env(env_var, value.strip())

    log(("AWS Bedrock credentials saved successfully!", "green"))


def _configure_google_vertex() -> None:
    import os

    from klaude_code.auth.env import get_auth_env, set_auth_env

    fields: list[tuple[str, str]] = [
        ("GOOGLE_APPLICATION_CREDENTIALS", "Enter GOOGLE_APPLICATION_CREDENTIALS"),
        ("GOOGLE_CLOUD_PROJECT", "Enter GOOGLE_CLOUD_PROJECT"),
        ("GOOGLE_CLOUD_LOCATION", "Enter GOOGLE_CLOUD_LOCATION"),
    ]

    for env_var, prompt in fields:
        current_value = os.environ.get(env_var) or get_auth_env(env_var)
        if current_value:
            log(f"Current {env_var}: {current_value}")
            if not typer.confirm("Do you want to update it?"):
                continue

        value = typer.prompt(prompt)
        if not value.strip():
            log((f"Error: {env_var} cannot be empty", "red"))
            raise typer.Exit(1)

        set_auth_env(env_var, value.strip())

    log(("Google Vertex credentials saved successfully!", "green"))


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
        case "github-copilot" | "copilot":
            from klaude_code.auth.copilot.oauth import CopilotOAuth
            from klaude_code.auth.copilot.token_manager import CopilotTokenManager

            token_manager = CopilotTokenManager()

            if token_manager.is_logged_in():
                state = token_manager.get_state()
                if state and not state.is_expired():
                    log(("You are already logged in to GitHub Copilot.", "green"))
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
        case "aws-bedrock" | "aws_bedrock" | "bedrock":
            _configure_aws_bedrock()
        case "google-vertex" | "google_vertex" | "vertex":
            _configure_google_vertex()
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


def _remove_auth_env(env_var: str, label: str) -> None:
    """Remove a configured auth env var from klaude-auth.json."""
    from klaude_code.auth.env import delete_auth_env, get_auth_env

    current_value = get_auth_env(env_var)
    if not current_value:
        log(f"No configured {env_var} found.")
        return

    if typer.confirm(f"Are you sure you want to remove configured {label} ({env_var})?"):
        delete_auth_env(env_var)
        log((f"Removed configured {env_var}.", "green"))


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
        case "github-copilot" | "copilot":
            from klaude_code.auth.copilot.token_manager import CopilotTokenManager

            token_manager = CopilotTokenManager()

            if not token_manager.is_logged_in():
                log("You are not logged in to GitHub Copilot.")
                return

            if typer.confirm("Are you sure you want to logout from GitHub Copilot?"):
                token_manager.delete()
                log(("Logged out from GitHub Copilot.", "green"))
        case "aws-bedrock" | "aws_bedrock" | "bedrock":
            from klaude_code.auth.env import delete_auth_env, get_auth_env

            bedrock_vars = (
                "AWS_BEDROCK_ACCESS_KEY_ID",
                "AWS_BEDROCK_SECRET_ACCESS_KEY",
                "AWS_BEDROCK_REGION",
            )
            has_any = any(get_auth_env(v) for v in bedrock_vars)
            if not has_any:
                log("No configured AWS Bedrock credentials found.")
                return

            if typer.confirm("Are you sure you want to remove configured AWS Bedrock credentials?"):
                for v in bedrock_vars:
                    delete_auth_env(v)
                log(("Removed configured AWS Bedrock credentials.", "green"))
        case "google-vertex" | "google_vertex" | "vertex":
            from klaude_code.auth.env import delete_auth_env, get_auth_env

            vertex_vars = (
                "GOOGLE_APPLICATION_CREDENTIALS",
                "GOOGLE_CLOUD_PROJECT",
                "GOOGLE_CLOUD_LOCATION",
            )
            has_any = any(get_auth_env(v) for v in vertex_vars)
            if not has_any:
                log("No configured Google Vertex credentials found.")
                return

            if typer.confirm("Are you sure you want to remove configured Google Vertex credentials?"):
                for v in vertex_vars:
                    delete_auth_env(v)
                log(("Removed configured Google Vertex credentials.", "green"))
        case _:
            from klaude_code.config.builtin_config import SUPPORTED_API_KEYS

            env_var: str | None = None
            label: str | None = None
            provider_lower = provider.lower()
            provider_upper = provider.upper()
            for key_info in SUPPORTED_API_KEYS:
                name_lower = key_info.name.lower()
                if key_info.env_var == provider_upper or name_lower == provider_lower:
                    env_var = key_info.env_var
                    label = key_info.name
                    break
                if name_lower.startswith(provider_lower) or provider_lower in name_lower.split():
                    env_var = key_info.env_var
                    label = key_info.name
                    break

            if env_var and label:
                _remove_auth_env(env_var, label)
            else:
                log((f"Error: Unknown provider '{provider}'", "red"))
                raise typer.Exit(1)
