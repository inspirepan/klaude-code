"""Authentication commands for CLI."""

from typing import Any, cast

import typer


class _LazyProviderHelp:
    _value: str | None = None

    def _resolve(self) -> str:
        if self._value is None:
            from klaude_code.config.builtin_config import SUPPORTED_API_KEYS

            names = ["codex", "claude", "github-copilot", "copilot"] + [
                k.name.split()[0].lower() for k in SUPPORTED_API_KEYS
            ]
            self._value = f"Provider name ({', '.join(names)})"
        return self._value

    def __str__(self) -> str:
        return self._resolve()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._resolve(), name)


def login_command(
    provider: str | None = typer.Argument(None, help=cast(str, _LazyProviderHelp())),
) -> None:
    """Login to a provider or configure API keys."""
    from klaude_code.app.auth_flow import execute_login
    from klaude_code.tui.command.auth_selector import select_provider

    if provider is None:
        provider = select_provider()
        if provider is None:
            return

    execute_login(provider)


def logout_command(
    provider: str | None = typer.Argument(None, help="Provider to logout (codex|claude|github-copilot|copilot)"),
) -> None:
    """Logout from a provider."""
    from klaude_code.app.auth_flow import execute_logout
    from klaude_code.tui.command.auth_selector import select_provider

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
