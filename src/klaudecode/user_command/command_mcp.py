from typing import Generator

from rich.abc import RichRenderable
from rich.text import Text

from ..agent import AgentState
from ..mcp.mcp_config import MCPConfigManager
from ..message import UserMessage
from ..tui import ColorStyle, console, render_suffix
from ..user_input import Command, CommandHandleOutput, UserInput


class MCPCommand(Command):
    def get_name(self) -> str:
        return 'mcp'

    def get_command_desc(self) -> str:
        return 'Initialize MCP servers'

    async def handle(self, agent_state: 'AgentState', user_input: UserInput) -> CommandHandleOutput:
        command_handle_output = await super().handle(agent_state, user_input)

        # Initialize MCP manager
        init_success = await agent_state.initialize_mcp()

        # Load MCP configuration
        config_manager = MCPConfigManager(agent_state.session.work_dir)
        mcp_config = config_manager.load_config()

        # Store data for rendering (convert to dict for JSON serialization)
        command_handle_output.user_msg.set_extra_data('mcp_init_success', init_success)
        command_handle_output.user_msg.set_extra_data('mcp_config', mcp_config.model_dump() if mcp_config else {})

        # Store manager status instead of the object itself to avoid serialization issues
        mcp_manager_status = None
        if agent_state.mcp_manager and hasattr(agent_state.mcp_manager, 'is_initialized'):
            mcp_manager_status = agent_state.mcp_manager.is_initialized()
        status_text = Text()
        if init_success:
            status_text.append('MCP Manager: ')
            status_text.append('✓ Initialized', style=ColorStyle.SUCCESS)
        else:
            status_text.append('MCP Manager: ')
            status_text.append('✗ Failed', style=ColorStyle.ERROR)
        if mcp_manager_status is not None:
            status_text.append(' | Status: ')
            if mcp_manager_status:
                status_text.append('Running', style=ColorStyle.SUCCESS)
            else:
                status_text.append('Not running', style=ColorStyle.WARNING)
        console.print(render_suffix(status_text))
        return command_handle_output

    def render_user_msg_suffix(self, user_msg: UserMessage) -> Generator[RichRenderable, None, None]:
        init_success = user_msg.get_extra_data('mcp_init_success')
        mcp_config_dict = user_msg.get_extra_data('mcp_config')

        if init_success is None or mcp_config_dict is None:
            return

        # Simple status display
        status_text = Text()

        # Show configured servers
        mcp_servers = mcp_config_dict.get('mcpServers', {})
        if mcp_servers:
            status_text.append(f'MCP servers ({len(mcp_servers)}): ')
            server_names = list(mcp_servers.keys())
            status_text.append(', '.join(server_names), style=ColorStyle.INFO.bold)
        else:
            status_text.append('No servers configured', style=ColorStyle.INFO.bold)

        yield render_suffix(status_text)
