from ..agent import AgentState
from ..user_input import Command, CommandHandleOutput, UserInput


class ContinueCommand(Command):
    def get_name(self) -> str:
        return 'continue'

    def get_command_desc(self) -> str:
        return 'Request LLM without new user message.'

    async def handle(self, agent_state: 'AgentState', user_input: UserInput) -> CommandHandleOutput:
        command_handle_output = await super().handle(agent_state, user_input)
        command_handle_output.need_agent_run = True
        return command_handle_output
