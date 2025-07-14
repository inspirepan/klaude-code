import typer

edit_app = typer.Typer(help='Edit configuration files')


@edit_app.command('config')
def edit_config():
    """Edit global configuration file"""
    from ..config import FileConfigSource

    FileConfigSource.edit_config_file()


@edit_app.command('mcp')
def edit_mcp():
    """Edit MCP configuration file"""
    from ..mcp.mcp_config import MCPConfigManager

    config_manager = MCPConfigManager()
    config_manager.edit_config_file()
