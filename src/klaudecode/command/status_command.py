from typing import TYPE_CHECKING, Generator

from rich.abc import RichRenderable

from ..config import ConfigModel
from ..message import UserMessage
from ..tui import render_suffix
from ..user_input import Command, CommandHandleOutput, UserInput

if TYPE_CHECKING:
    from ..agent import Agent


class StatusCommand(Command):
    def get_name(self) -> str:
        return 'status'

    def get_command_desc(self) -> str:
        return 'Show the current setup'

    async def handle(self, agent: 'Agent', user_input: UserInput) -> CommandHandleOutput:
        command_handle_output = await super().handle(agent, user_input)
        command_handle_output.user_msg.set_extra_data('status', agent.config)
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
