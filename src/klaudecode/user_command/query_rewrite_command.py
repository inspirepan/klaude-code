from abc import ABC, abstractmethod

from ..agent import AgentState
from ..user_input import Command, CommandHandleOutput, UserInput


class QueryRewriteCommand(Command, ABC):
    @abstractmethod
    def get_query_content(self, user_input: UserInput) -> str:
        pass

    async def handle(self, agent_state: 'AgentState', user_input: UserInput) -> CommandHandleOutput:
        command_handle_output = await super().handle(agent_state, user_input)
        command_handle_output.need_agent_run = command_handle_output.user_msg.is_valid()
        command_handle_output.user_msg.content = self.get_query_content(user_input)
        if user_input.cleaned_input:
            command_handle_output.user_msg.content += 'Additional Instructions:\n' + user_input.cleaned_input
        return command_handle_output
