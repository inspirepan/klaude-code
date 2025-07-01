import asyncio
from contextlib import AsyncExitStack
from typing import Any, Dict

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from ..tui import ColorStyle, Text, console
from ..utils.exception import format_exception
from .mcp_config import MCPConfigManager


class MCPClient:
    """New MCP client using official MCP library"""

    def __init__(self, work_dir: str = None):
        self.work_dir = work_dir
        self.config_manager = MCPConfigManager(work_dir)
        self.clients: Dict[str, ClientSession] = {}
        self.exit_stack = AsyncExitStack()
        self.tools: Dict[str, Any] = {}
        self._initialized = False

    async def initialize(self) -> bool:
        """Initialize MCP client"""
        if self._initialized:
            return True

        config = self.config_manager.load_config()
        if not config.mcpServers:
            console.print(Text('No MCP servers configured', style=ColorStyle.WARNING))
            return True

        # Connect to all configured servers
        success_count = 0
        sussess_servers = []
        console.print()
        for server_name, server_config in config.mcpServers.items():
            try:
                console.print(Text.assemble('Connecting to MCP server: ', (server_name, ColorStyle.INFO.bold)))
                server_params = StdioServerParameters(command=server_config.command, args=server_config.args or [], env=server_config.env or {})
                client_transport = await asyncio.wait_for(self.exit_stack.enter_async_context(stdio_client(server_params)), timeout=10.0)
                client_session = await asyncio.wait_for(self.exit_stack.enter_async_context(ClientSession(client_transport[0], client_transport[1])), timeout=5.0)
                await asyncio.wait_for(client_session.initialize(), timeout=10.0)
                self.clients[server_name] = client_session
                tools_result = await asyncio.wait_for(client_session.list_tools(), timeout=5.0)
                for mcp_tool in tools_result.tools:
                    tool_key = f'{server_name}::{mcp_tool.name}'
                    self.tools[tool_key] = {
                        'server_name': server_name,
                        'session': client_session,
                        'tool': mcp_tool,
                        'name': mcp_tool.name,
                        'description': mcp_tool.description,
                        'inputSchema': mcp_tool.inputSchema,
                    }
                success_count += 1
                sussess_servers.append(server_name)
            except asyncio.TimeoutError:
                console.print(Text(f'Timeout connecting to MCP server {server_name}', style=ColorStyle.ERROR))
                continue
            except Exception as e:
                console.print(Text(f'Failed to connect to MCP server {server_name}: {format_exception(e)}', style=ColorStyle.ERROR))
                continue
        if success_count > 0:
            sussess_server_names = ', '.join(sussess_servers)
            console.print(
                Text.assemble(f'Connected to {success_count}/{len(config.mcpServers)} MCP servers: ', (sussess_server_names, ColorStyle.INFO.bold), style=ColorStyle.SUCCESS)
            )
        console.print()
        self._initialized = True
        return True

    async def shutdown(self):
        """Shutdown MCP client"""
        try:
            await self.exit_stack.aclose()
        except RuntimeError as e:
            if 'Attempted to exit cancel scope in a different task' in str(e):
                # This can occur during KeyboardInterrupt and can be safely ignored
                pass
            else:
                raise

        self.clients.clear()
        self.tools.clear()
        self._initialized = False

    def get_all_tools(self) -> Dict[str, Any]:
        """Get all MCP tools"""
        return {key: tool_info['tool'] for key, tool_info in self.tools.items()}

    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Execute MCP tool"""
        # Find tool and server
        tool_info = None
        for _, info in self.tools.items():
            if info['name'] == tool_name:
                tool_info = info
                break

        if not tool_info:
            raise ValueError(f'Tool {tool_name} not found in any connected server')

        try:
            # Execute MCP tool with timeout
            result = await asyncio.wait_for(tool_info['session'].call_tool(tool_name, arguments), timeout=30.0)

            # Process result
            if result.content:
                content_parts = []
                for content in result.content:
                    if hasattr(content, 'text'):
                        content_parts.append(content.text)
                    else:
                        content_parts.append(str(content))
                return {'content': [{'type': 'text', 'text': '\n'.join(content_parts)}]}
            else:
                return {'content': [{'type': 'text', 'text': 'Tool executed successfully'}]}

        except asyncio.TimeoutError:
            raise RuntimeError(f'MCP tool {tool_name} timed out after 30 seconds')
        except Exception as e:
            raise RuntimeError(f'Error calling MCP tool {tool_name}: {format_exception(e)}')
