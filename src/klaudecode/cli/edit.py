import typer
from typing import Optional

edit_app = typer.Typer(help='Edit configuration files', invoke_without_command=True)


@edit_app.callback()
def edit_main(
    ctx: typer.Context,
    config_name: Optional[str] = typer.Argument(None, help="Configuration name (e.g., 'anthropic' for config_anthropic.json) or 'mcp' for MCP configuration")
):
    """Edit configuration files
    
    Examples:
      klaude edit            # Edit default config.json
      klaude edit anthropic  # Edit config_anthropic.json  
      klaude edit mcp        # Edit MCP configuration
    """
    # Only process when no subcommand is invoked
    if ctx.invoked_subcommand is None:
        if config_name == 'mcp':
            # Special case: edit MCP configuration
            edit_mcp_config()
        else:
            # Edit regular configuration file (default or named)
            edit_config_file(config_name)


def edit_config_file(config_name: Optional[str]):
    """Edit configuration file"""
    from ..config.file_config_source import FileConfigSource, resolve_config_path
    from ..tui import ColorStyle, Text, console
    
    if config_name is None:
        # Edit default config.json
        FileConfigSource.edit_config_file()
    else:
        # Edit or create config_{config_name}.json
        import os
        import sys

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


def edit_mcp_config():
    """Edit MCP configuration file"""
    from ..mcp.mcp_config import MCPConfigManager

    config_manager = MCPConfigManager()
    config_manager.edit_config_file()