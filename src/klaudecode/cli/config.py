from pathlib import Path

import typer
from rich.rule import Rule
from rich.text import Text

from ..config import ConfigManager
from ..config.file_config_source import FileConfigSource
from ..tui import ColorStyle, console


def setup_config(**kwargs) -> ConfigManager:
    config_manager = ConfigManager.setup(**kwargs)
    config_model = config_manager.get_config_model()
    if hasattr(config_model, 'theme') and config_model.theme:
        console.set_theme(config_model.theme.value)
    return config_manager


config_app = typer.Typer(help='Manage global configuration', invoke_without_command=True)


@config_app.callback()
def config_callback(ctx: typer.Context):
    """Manage global configuration"""
    if ctx.invoked_subcommand is None:
        # Default action: show config
        config_show()


def find_all_config_files() -> list[Path]:
    """Find all config files in ~/.klaude/ directory"""
    klaude_dir = Path.home() / '.klaude'
    if not klaude_dir.exists():
        return []

    config_files = []

    # Find all config_*.json files
    for config_file in klaude_dir.glob('config_*.json'):
        config_files.append(config_file)

    return sorted(config_files)


def display_config_file(config_path: Path) -> None:
    """Display configuration for a single file using ConfigManager styling"""
    try:
        # Create a minimal ConfigManager with only defaults and the specific config file
        # This shows what this config file provides plus defaults for missing values
        from ..config.default_source import DefaultConfigSource

        sources = [DefaultConfigSource(), FileConfigSource(str(config_path))]

        # Create a custom ConfigManager that skips API key validation
        config_manager = ConfigManager.__new__(ConfigManager)
        config_manager.sources = sources
        config_manager._merged_config_model = config_manager._merge_config_models()
        config_manager._config_path = config_path

        console.print(Text(config_path.name[7:-5], style=ColorStyle.HIGHLIGHT.bold))
        console.print(config_manager)

    except Exception as e:
        console.print(Text(f'Error reading {config_path.name}: {e}', style=ColorStyle.ERROR))


@config_app.command('show')
def config_show():
    """
    Show all available configurations
    """
    # Show the current active configuration first
    config_manager = setup_config()
    console.print(Text('default', style=ColorStyle.HIGHLIGHT.bold))
    console.print(config_manager)
    console.print()

    # Find and display all config files
    config_files = find_all_config_files()

    if not config_files:
        return
    console.print(Text('CONFIG FILES', style=ColorStyle.SUCCESS.bold))
    console.print(Text.assemble('Run ', ('klaude --config <config_name>', ColorStyle.INLINE_CODE), ' to use a specific config file', style=ColorStyle.HINT))
    console.print(Text.assemble('Run ', ('klaude config edit <config_name>', ColorStyle.INLINE_CODE), ' to edit a specific config file', style=ColorStyle.HINT))
    console.print(Rule(style=ColorStyle.LINE, characters='╌'))

    for config_file in config_files:
        console.print()
        display_config_file(config_file)


@config_app.command('edit')
def config_edit(config_name: str = typer.Argument(None, help="Configuration name (e.g., 'anthropic' for config_anthropic.json)")):
    """
    Init or edit configuration file

    If no config_name is provided, edits the default config.json.
    If config_name is provided, edits config_{config_name}.json.
    """
    if config_name is None:
        # Edit default config.json
        FileConfigSource.edit_config_file()
    else:
        # Edit or create config_{config_name}.json
        import os
        import sys

        from ..config.file_config_source import resolve_config_path

        config_path = resolve_config_path(config_name)

        # Create directory if it doesn't exist
        config_path.parent.mkdir(parents=True, exist_ok=True)

        # Create file with example content if it doesn't exist
        if not config_path.exists():
            console.print(Text(f'Creating new config file: {config_path}', style=ColorStyle.SUCCESS))
            FileConfigSource.create_example_config(config_path)

        # Open the file in editor
        console.print(Text(f'Opening config file: {config_path}', style=ColorStyle.SUCCESS))
        editor = os.getenv('EDITOR', 'vi' if sys.platform != 'darwin' else 'open')
        os.system(f'{editor} {config_path}')
