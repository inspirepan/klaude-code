"""Authentication commands for CLI."""

import typer

from klaude_code.app.auth_flow import execute_login, execute_logout
from klaude_code.tui.command.auth_selector import select_provider


def _build_provider_help() -> str:
    from klaude_code.config.builtin_config import SUPPORTED_API_KEYS

    names = ["codex", "claude", "copilot"] + [k.name.split()[0].lower() for k in SUPPORTED_API_KEYS]
    return f"Provider name ({', '.join(names)})"


def login_command(
    provider: str | None = typer.Argument(None, help=_build_provider_help()),
) -> None:
    """Login to a provider or configure API keys."""
    if provider is None:
        provider = select_provider()
        if provider is None:
            return

    execute_login(provider)


def logout_command(
    provider: str | None = typer.Argument(None, help="Provider to logout (codex|claude|copilot)"),
) -> None:
    """Logout from a provider."""
    if provider is None:
        provider = select_provider(include_api_keys=False, prompt="Select provider to logout:")
        if provider is None:
            return

    execute_logout(provider)


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
