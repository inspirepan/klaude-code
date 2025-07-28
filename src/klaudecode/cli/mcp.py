import asyncio

from ..tui import ColorStyle, Text, console
from ..utils.exception import format_exception
from .config import setup_config


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
            console.print(Text.assemble(
                ('Error connecting to MCP servers: ', ColorStyle.ERROR),
                format_exception(e)
            ))
        finally:
            await mcp_manager.shutdown()

    asyncio.run(show_mcp_info())


def mcp_edit():
    """Init or edit MCP configuration file"""
    from ..mcp.mcp_config import MCPConfigManager

    config_manager = MCPConfigManager()
    config_manager.edit_config_file()
