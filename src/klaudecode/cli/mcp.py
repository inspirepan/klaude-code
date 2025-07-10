import asyncio

import typer

from ..tui import ColorStyle, Text, console
from ..utils.exception import format_exception
from .config import setup_config

mcp_app = typer.Typer(help='Manage MCP (Model Context Protocol) servers', invoke_without_command=True)


@mcp_app.callback()
def mcp_callback(ctx: typer.Context):
    """Manage MCP (Model Context Protocol) servers"""
    if ctx.invoked_subcommand is None:
        # Default action: show MCP info
        mcp_show()


@mcp_app.command('show')
def mcp_show():
    """Show current MCP configuration and available tools"""
    from ..mcp.mcp_tool import MCPManager

    _ = setup_config()

    async def show_mcp_info():
        mcp_manager = MCPManager()
        try:
            await mcp_manager.initialize()
            console.print(mcp_manager)
        except Exception as e:
            console.print(Text(f'Error connecting to MCP servers: {format_exception(e)}', style=ColorStyle.ERROR))
        finally:
            await mcp_manager.shutdown()

    asyncio.run(show_mcp_info())


@mcp_app.command('edit')
def mcp_edit():
    """Init or edit MCP configuration file"""
    from ..mcp.mcp_config import MCPConfigManager

    config_manager = MCPConfigManager()
    config_manager.edit_config_file()
