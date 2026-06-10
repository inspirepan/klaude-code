"""Authentication commands for CLI."""

from typing import Any, cast

import typer


class _LazyProviderHelp:
    _value: str | None = None

    def _resolve(self) -> str:
        if self._value is None:
            from klaude_code.config.builtin_config import SUPPORTED_API_KEYS

            names = ["codex"] + [k.name.split()[0].lower() for k in SUPPORTED_API_KEYS]
            self._value = f"Provider name ({', '.join(names)})"
        return self._value

    def __str__(self) -> str:
        return self._resolve()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._resolve(), name)


def login_command(
    provider: str | None = typer.Argument(None, help=cast(str, _LazyProviderHelp())),
    name: str | None = typer.Option(None, "--name", "-n", help="Codex account name"),
) -> None:
    """Login to a provider or configure API keys."""
    from klaude_code.app.auth_flow import execute_login
    from klaude_code.tui.command.auth_selector import select_provider

    if provider is None:
        provider = select_provider()
        if provider is None:
            return

    if name is not None:
        execute_login(provider, account_name=name)
    else:
        execute_login(provider)


def logout_command(
    provider: str | None = typer.Argument(None, help=cast(str, _LazyProviderHelp())),
    account: str | None = typer.Argument(None, help="Codex account name"),
    all_accounts: bool = typer.Option(False, "--all", help="Logout all Codex accounts"),
) -> None:
    """Logout from a provider."""
    from klaude_code.app.auth_flow import execute_logout
    from klaude_code.tui.command.auth_selector import select_provider

    if provider is None:
        provider = select_provider(include_api_keys=True, configured_only=True, prompt="Select provider to logout:")
        if provider is None:
            return

    if account is not None or all_accounts:
        execute_logout(provider, account_name=account, all_accounts=all_accounts)
    else:
        execute_logout(provider)


def list_command(
    provider: str | None = typer.Argument(None, help="Provider name (default: codex)"),
) -> None:
    """List logged-in OAuth accounts."""
    from klaude_code.app.auth_flow import execute_list

    execute_list(provider)


def switch_command(
    provider_or_account: str | None = typer.Argument(None, help="Provider name or Codex account name"),
    account: str | None = typer.Argument(None, help="Account name"),
) -> None:
    """Switch active OAuth account."""
    from klaude_code.app.auth_flow import execute_switch

    if provider_or_account is None:
        execute_switch("codex")
        return

    if account is None and provider_or_account.lower() != "codex":
        execute_switch("codex", account_name=provider_or_account)
        return

    execute_switch(provider_or_account, account_name=account)


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
    auth_app.command("list")(list_command)
    auth_app.command("switch")(switch_command)
    app.add_typer(auth_app, name="auth")
