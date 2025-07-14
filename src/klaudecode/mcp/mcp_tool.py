import asyncio
import concurrent.futures
import json
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field
from rich.console import Group, Text
from rich.pretty import Pretty
from rich.table import Table

from ..message import ToolCall, ToolMessage, register_tool_result_renderer
from ..tool import Tool, ToolInstance
from ..tui import ColorStyle, console, render_grid, render_suffix
from ..utils.exception import format_exception
from .mcp_client import MCPClient


@register_tool_result_renderer('mcp__')
def render_mcp_tool_result(msg: ToolMessage):
    content = msg.content

    try:
        if isinstance(content, str) and content.strip().startswith('{'):
            parsed = json.loads(content)
            yield render_suffix(
                Pretty(
                    parsed,
                    max_depth=4,
                    max_length=4,
                    max_string=100,
                )
            )
        elif isinstance(content, dict):
            yield render_suffix(
                Pretty(
                    content,
                    max_depth=4,
                    max_length=4,
                    max_string=100,
                )
            )
        else:
            yield render_suffix(Text(str(content)))
    except (json.JSONDecodeError, TypeError):
        yield render_suffix(Text(str(content)))


class MCPToolWrapper(Tool):
    # Dynamic properties
    name: str = ''
    desc: str = ''
    parallelable: bool = True
    timeout = 300

    # MCP specific properties
    mcp_tool_name: str = ''
    mcp_input_schema: Dict[str, Any] = {}
    server_name: str = ''

    @classmethod
    def create_from_mcp_tool(cls, tool_info: Dict[str, Any], mcp_client: MCPClient):
        """Create wrapper tool class from MCP tool info"""

        mcp_tool = tool_info['tool']
        server_name = tool_info['server_name']

        # Dynamically create Input class
        input_properties = mcp_tool.inputSchema.get('properties', {})
        required_fields = mcp_tool.inputSchema.get('required', [])

        # Build Pydantic field annotations
        annotations = {}
        field_defaults = {}

        for prop_name, prop_schema in input_properties.items():
            field_description = prop_schema.get('description', '')
            is_required = prop_name in required_fields

            # Infer Python type from schema type
            if prop_schema.get('type') == 'integer':
                field_type = int
            elif prop_schema.get('type') == 'number':
                field_type = float
            elif prop_schema.get('type') == 'boolean':
                field_type = bool
            elif prop_schema.get('type') == 'array':
                field_type = list
            elif prop_schema.get('type') == 'object':
                field_type = dict
            else:
                field_type = str  # Default to string type

            # Set type annotations
            annotations[prop_name] = field_type

            # Set field default values
            if is_required:
                field_defaults[prop_name] = Field(..., description=field_description)
            else:
                field_defaults[prop_name] = Field(default=None, description=field_description)

        # Create dynamic Input class
        class_dict = field_defaults.copy()
        class_dict['__annotations__'] = annotations
        DynamicInput = type('Input', (BaseModel,), class_dict)

        # Create dynamic tool class
        class_name = f'MCP_{server_name}_{mcp_tool.name.replace("-", "_").replace(".", "_")}'

        class_attrs = {
            'name': f'mcp__{mcp_tool.name}',
            'desc': f'[MCP:{server_name}] {mcp_tool.description}',
            'parallelable': True,
            'timeout': 300,
            'mcp_tool_name': mcp_tool.name,
            'mcp_input_schema': mcp_tool.inputSchema,
            'server_name': server_name,
            'Input': DynamicInput,
            '_mcp_client': mcp_client,
        }

        return type(class_name, (MCPToolWrapper,), class_attrs)

    @classmethod
    def invoke(cls, tool_call: ToolCall, instance: 'ToolInstance'):
        """Execute MCP tool (sync wrapper for compatibility)"""
        try:
            # Parse input parameters
            args_dict = json.loads(tool_call.tool_args)

            # Create a new event loop for this thread if none exists
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # If we're in an async context, create a new thread
                    with concurrent.futures.ThreadPoolExecutor() as executor:
                        future = executor.submit(cls._sync_mcp_call, args_dict)
                        result = future.result(timeout=cls.timeout)
                else:
                    # Use the existing loop
                    result = loop.run_until_complete(asyncio.wait_for(cls._call_mcp_tool_async(args_dict), timeout=cls.timeout))
            except RuntimeError:
                # No event loop in current thread, create a new one
                result = asyncio.run(asyncio.wait_for(cls._call_mcp_tool_async(args_dict), timeout=cls.timeout))

            # Set result
            cls._process_result(result, instance)

        except Exception as e:
            instance.tool_result().set_error_msg(f'MCP tool error: {str(e)}')

    @classmethod
    def _sync_mcp_call(cls, args_dict: Dict[str, Any]) -> Dict[str, Any]:
        """Synchronous wrapper for MCP tool call"""
        return asyncio.run(asyncio.wait_for(cls._call_mcp_tool_async(args_dict), timeout=cls.timeout))

    @classmethod
    async def invoke_async(cls, tool_call: ToolCall, instance: 'ToolInstance'):
        """Execute MCP tool (native async implementation)"""
        try:
            # Parse input parameters
            args_dict = json.loads(tool_call.tool_args)

            # Call MCP tool directly with proper timeout handling
            result = await asyncio.wait_for(cls._call_mcp_tool_async(args_dict), timeout=cls.timeout)

            # Set result
            cls._process_result(result, instance)

        except asyncio.TimeoutError:
            instance.tool_result().set_error_msg(f'MCP tool {cls.mcp_tool_name} timed out after {cls.timeout}s')
        except Exception as e:
            instance.tool_result().set_error_msg(f'MCP tool error: {str(e)}')

    @classmethod
    def _process_result(cls, result: Dict[str, Any], instance: 'ToolInstance'):
        """Process MCP tool result and set it to instance"""
        if isinstance(result, dict):
            if 'content' in result:
                # Process content array
                content_parts = []
                for content_item in result['content']:
                    if content_item.get('type') == 'text':
                        content_parts.append(content_item.get('text', ''))
                    elif content_item.get('type') == 'image':
                        content_parts.append(f'[Image: {content_item.get("data", "base64 data")}]')
                    else:
                        content_parts.append(str(content_item))
                instance.tool_result().set_content('\n'.join(content_parts))
            else:
                instance.tool_result().set_content(json.dumps(result, indent=2, ensure_ascii=False))
        else:
            instance.tool_result().set_content(str(result))

    @classmethod
    async def _call_mcp_tool_async(cls, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Asynchronously execute MCP tool"""
        return await cls._mcp_client.call_tool(cls.mcp_tool_name, arguments)


class MCPManager:
    """MCP manager using official MCP library"""

    def __init__(self, work_dir: str = None):
        self.work_dir = work_dir
        self.mcp_client: Optional[MCPClient] = None
        self.mcp_tools: Dict[str, type] = {}
        self._initialized = False

    async def initialize(self) -> bool:
        """Initialize MCP manager"""
        if self._initialized:
            return True

        self.mcp_client = MCPClient(self.work_dir)
        success = await self.mcp_client.initialize()

        if success:
            # Get all MCP tools and create wrappers
            for tool_key, tool_info in self.mcp_client.tools.items():
                try:
                    wrapper_class = MCPToolWrapper.create_from_mcp_tool(tool_info, self.mcp_client)
                    self.mcp_tools[wrapper_class.name] = wrapper_class
                except Exception as e:
                    console.print(Text(f'Failed to create wrapper for MCP tool {tool_info["name"]}: {format_exception(e)}', style=ColorStyle.ERROR))

        self._initialized = success
        return success

    async def shutdown(self):
        """Shutdown MCP manager"""
        if self.mcp_client:
            await self.mcp_client.shutdown()
        self.mcp_tools.clear()
        self._initialized = False

    def get_mcp_tools(self) -> list:
        """Get all MCP tool class list"""
        return list(self.mcp_tools.values())

    def is_initialized(self) -> bool:
        """Check if initialized"""
        return self._initialized

    def __rich_console__(self, console, options):
        """Rich console rendering for MCP configuration and tools"""
        from .mcp_config import MCPConfigManager

        config_manager = MCPConfigManager()
        config = config_manager.load_config()

        yield Text.assemble(
            '\nMCP configuration file path: ',
            (str(config_manager.get_config_path()), ColorStyle.SUCCESS),
            '\n',
        )

        # Show configured servers
        if not config.mcpServers:
            yield Text('No MCP servers configured', style=ColorStyle.WARNING)
            return

        yield Text('\nConfigured MCP servers:', style=ColorStyle.MAIN.bold)

        yield render_grid(
            [
                [Text(name, style=ColorStyle.INFO.bold), Text(server_config.command), Text(' '.join(server_config.args) if server_config.args else '')]
                for name, server_config in config.mcpServers.items()
            ]
        )

        # Show tools if initialized
        if self._initialized and self.mcp_client and self.mcp_client.tools:
            yield Text(f'\nAvailable MCP tools ({len(self.mcp_client.tools)}):\n', style=ColorStyle.SUCCESS.bold)

            # Group tools by server
            tools_by_server = {}
            for tool_info in self.mcp_client.tools.values():
                server_name = tool_info['server_name']
                if server_name not in tools_by_server:
                    tools_by_server[server_name] = []
                tools_by_server[server_name].append(tool_info)

            main_table = Table.grid(padding=(0, 1))
            main_table.add_column(no_wrap=True)
            main_table.add_column(overflow='fold')

            for server_name, tools in tools_by_server.items():
                main_table.add_row(Text.assemble((server_name, ColorStyle.INFO.bold), f'({len(tools)} tools)'), '')

                for tool_info in tools:
                    tool_name = tool_info['name']
                    tool_desc = tool_info['description'] or 'No description'
                    mcp_tool = tool_info['tool']
                    input_schema = mcp_tool.inputSchema
                    properties = input_schema.get('properties', {})
                    required_fields = input_schema.get('required', [])

                    if properties:
                        param_table = Table.grid(padding=(0, 1))
                        param_table.add_column(no_wrap=True)
                        param_table.add_column(no_wrap=True)
                        param_table.add_column(overflow='fold')
                        for param_name, param_schema in properties.items():
                            param_type = param_schema.get('type', 'string')
                            param_desc = param_schema.get('description', '')
                            is_required = param_name in required_fields
                            required_indicator = '*' if is_required else ''
                            param_table.add_row(Text(f'· {param_name}{required_indicator}', style=ColorStyle.HIGHLIGHT), Text(param_type, style=ColorStyle.INFO), Text(param_desc))
                        main_table.add_row(Text(tool_name, style=ColorStyle.SUCCESS), Group(tool_desc, '', param_table, ''))
                    else:
                        main_table.add_row('', tool_desc)

            main_table.add_row('', '')

            yield main_table
        elif not self._initialized:
            yield Text('\nMCP tools not loaded (manager not initialized)', style=ColorStyle.WARNING)
        else:
            yield Text('\nUnable to connect to any MCP servers or no tools available', style=ColorStyle.WARNING)
