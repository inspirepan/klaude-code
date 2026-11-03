"""Authentication commands for CLI."""

import typer


def login_command(
    provider: str | None = typer.Argument(None, help="Provider name; omit to choose interactively"),
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
    provider: str | None = typer.Argument(None, help="Provider name; omit to choose interactively"),
) -> None:
    """Logout from a provider."""
    from klaude_code.app.auth_flow import execute_logout
    from klaude_code.tui.command.auth_selector import select_provider

    if provider is None:
        provider = select_provider(include_api_keys=True, configured_only=True, prompt="Select provider to logout:")
        if provider is None:
            return

    execute_logout(provider)


def register_auth_commands(app: typer.Typer) -> None:
    """Register provider login and logout as top-level commands."""
    app.command("login")(login_command)
    app.command("logout")(logout_command)
