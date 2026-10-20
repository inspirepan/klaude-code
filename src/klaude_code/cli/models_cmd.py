"""Model discovery without starting a server or an interactive session."""

from __future__ import annotations

import json
import sys
from typing import TYPE_CHECKING, Any

import typer

if TYPE_CHECKING:
    from klaude_code.config import Config


def build_model_inventory(config: Config, *, show_all: bool = False) -> list[dict[str, Any]]:
    providers = {provider.provider_name: provider for provider in config.provider_list}
    return [
        {
            "selector": entry.selector,
            "model_name": entry.model_name,
            "provider": entry.provider,
            "model_id": entry.model_id,
            "available": not (
                entry.disabled or providers[entry.provider].disabled or providers[entry.provider].is_api_key_missing()
            ),
            "disabled": entry.disabled or providers[entry.provider].disabled,
            "parameters": entry.model_dump(
                mode="json",
                include={
                    "thinking",
                    "effort",
                    "verbosity",
                    "fast_mode",
                    "cache_retention",
                    "supports_vision",
                    "provider_routing",
                },
                exclude_none=True,
            ),
        }
        for entry in config.iter_model_entries(only_available=not show_all, include_disabled=show_all)
    ]


def build_json_inventory(config: Config, *, show_all: bool = False) -> dict[str, Any]:
    from klaude_code.config.config import format_model_preference

    return {
        "models": build_model_inventory(config, show_all=show_all),
        "defaults": {
            "main_model": format_model_preference(config.main_model),
            "fast_model": format_model_preference(config.fast_model),
            "compact_model": format_model_preference(config.compact_model),
        },
    }


def models_command(
    json_: bool = typer.Option(False, "--json", help="Machine-readable models, parameters, and defaults"),
    show_all: bool = typer.Option(False, "--all", help="Include disabled models and unavailable providers"),
) -> None:
    """List configured models by provider, with parameters and agent-role bindings.

    Select a model with `klaude -m SELECTOR` or `klaude run --model SELECTOR`.
    This command reads local configuration only; it does not start the server.
    """
    from klaude_code.config import ConfigValidationError, load_config

    try:
        config = load_config()
    except ConfigValidationError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(1) from None

    if json_:
        typer.echo(json.dumps(build_json_inventory(config, show_all=show_all), ensure_ascii=False, indent=2))
        return

    from klaude_code.cli.list_model import display_models_and_providers
    from klaude_code.tui.terminal.color import is_light_terminal_background

    if config.theme is None and sys.stdout.isatty():
        detected = is_light_terminal_background()
        if detected is not None:
            config.theme = "light" if detected else "dark"
    if not config.iter_model_entries(only_available=not show_all, include_disabled=show_all):
        typer.echo("no models available; use `klaude models --all` to inspect configured models")
        return
    display_models_and_providers(config, show_all=show_all, show_credentials=False)


def register_models_command(app: typer.Typer) -> None:
    app.command("models")(models_command)
