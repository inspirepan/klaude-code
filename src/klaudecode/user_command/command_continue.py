from typing import TYPE_CHECKING

from ..user_input import Command, CommandHandleOutput, UserInput

if TYPE_CHECKING:
    from ..agent import Agent


class ContinueCommand(Command):
    def get_name(self) -> str:
        return 'continue'

    def get_command_desc(self) -> str:
        return 'Request LLM without new user message. NOTE: May cause error when no user message exists'

    async def handle(self, agent: 'Agent', user_input: UserInput) -> CommandHandleOutput:
        command_handle_output = await super().handle(agent, user_input)
        command_handle_output.need_agent_run = True
        return command_handle_output
