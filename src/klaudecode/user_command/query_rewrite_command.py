from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from ..user_input import Command, CommandHandleOutput, UserInput

if TYPE_CHECKING:
    from ..agent import Agent


class QueryRewriteCommand(Command, ABC):
    @abstractmethod
    def get_query_content(self, user_input: UserInput) -> str:
        pass

    async def handle(self, agent: 'Agent', user_input: UserInput) -> CommandHandleOutput:
        command_handle_output = await super().handle(agent, user_input)
        command_handle_output.need_agent_run = True
        command_handle_output.user_msg.content = self.get_query_content(user_input)
        if user_input.cleaned_input:
            command_handle_output.user_msg.content += 'Additional Instructions:\n' + user_input.cleaned_input
        return command_handle_output
