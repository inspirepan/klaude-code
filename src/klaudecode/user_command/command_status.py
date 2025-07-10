from typing import Generator

from rich.abc import RichRenderable

from ..agent import AgentState
from ..config import ConfigModel
from ..message import UserMessage
from ..tui import render_suffix
from ..user_input import Command, CommandHandleOutput, UserInput


class StatusCommand(Command):
    def get_name(self) -> str:
        return 'status'

    def get_command_desc(self) -> str:
        return 'Show the current setup'

    async def handle(self, agent_state: 'AgentState', user_input: UserInput) -> CommandHandleOutput:
        command_handle_output = await super().handle(agent_state, user_input)
        command_handle_output.user_msg.set_extra_data('status', agent_state.config)
        return command_handle_output

    def render_user_msg_suffix(self, user_msg: UserMessage) -> Generator[RichRenderable, None, None]:
        config_data = user_msg.get_extra_data('status')
        if config_data:
            if isinstance(config_data, ConfigModel):
                config_model = config_data
            elif isinstance(config_data, dict):
                config_model = ConfigModel.model_validate(config_data)
            else:
                return
            yield render_suffix(config_model)
