"""Configuration commands for CLI."""

import os
import subprocess
import sys

import typer

from klaude_code.config import config_path, create_example_config, example_config_path, load_config
from klaude_code.trace import log


def list_models() -> None:
    """List all models and providers configuration"""
    from klaude_code.cli.list_model import display_models_and_providers
    from klaude_code.ui.terminal.color import is_light_terminal_background

    config = load_config()

    # Auto-detect theme when not explicitly set in config, to match other CLI entrypoints.
    if config.theme is None:
        detected = is_light_terminal_background()
        if detected is True:
            config.theme = "light"
        elif detected is False:
            config.theme = "dark"

    display_models_and_providers(config)


def edit_config() -> None:
    """Open the configuration file in $EDITOR or default system editor"""
    editor = os.environ.get("EDITOR")

    # If no EDITOR is set, prioritize TextEdit on macOS
    if not editor:
        # Try common editors in order of preference on other platforms
        for cmd in [
            "code",
            "nvim",
            "vim",
            "nano",
        ]:
            try:
                subprocess.run(["which", cmd], check=True, capture_output=True)
                editor = cmd
                break
            except (subprocess.CalledProcessError, FileNotFoundError):
                continue

    # If no editor found, try platform-specific defaults
    if not editor:
        if sys.platform == "darwin":  # macOS
            editor = "open"
        elif sys.platform == "win32":  # Windows
            editor = "notepad"
        else:  # Linux and other Unix systems
            editor = "xdg-open"

    # Ensure config directory exists and create example config if needed
    config_path.parent.mkdir(parents=True, exist_ok=True)
    if create_example_config():
        log(f"Created example config: {example_config_path}", style="dim")

    # Decide which file to open
    target_path = config_path if config_path.exists() else example_config_path
    if target_path == example_config_path:
        log(f"Opening example config (copy to {config_path.name} to use)", style="yellow")

    try:
        if editor == "open -a TextEdit":
            subprocess.run(["open", "-a", "TextEdit", str(target_path)], check=True)
        elif editor in ["open", "xdg-open"]:
            # For open/xdg-open, we need to pass the file directly
            subprocess.run([editor, str(target_path)], check=True)
        else:
            subprocess.run([editor, str(target_path)], check=True)
    except subprocess.CalledProcessError as e:
        log((f"Error: Failed to open editor: {e}", "red"))
        raise typer.Exit(1) from None
    except FileNotFoundError:
        log((f"Error: Editor '{editor}' not found", "red"))
        log("Please install a text editor or set your $EDITOR environment variable")
        raise typer.Exit(1) from None


def register_config_commands(app: typer.Typer) -> None:
    """Register config commands to the given Typer app."""
    app.command("list")(list_models)
    app.command("config")(edit_config)
    app.command("conf", hidden=True)(edit_config)
