from typing import TYPE_CHECKING, Generator

from rich.abc import RichRenderable

from ..message import AgentUsage, UserMessage
from ..tui import render_suffix
from ..user_input import Command, CommandHandleOutput, UserInput

if TYPE_CHECKING:
    from ..agent import Agent


class CostCommand(Command):
    def get_name(self) -> str:
        return 'cost'

    def get_command_desc(self) -> str:
        return 'Show the total cost and duration of the current session'

    async def handle(self, agent: 'Agent', user_input: UserInput) -> CommandHandleOutput:
        command_handle_output = await super().handle(agent, user_input)
        command_handle_output.user_msg.set_extra_data('cost', agent.usage.model_dump())
        return command_handle_output

    def render_user_msg_suffix(self, user_msg: UserMessage) -> Generator[RichRenderable, None, None]:
        usage_data = user_msg.get_extra_data('cost')
        if usage_data:
            if isinstance(usage_data, dict):
                usage = AgentUsage.model_validate(usage_data)
                yield render_suffix(usage)
