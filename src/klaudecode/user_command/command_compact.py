from typing import Generator

from rich.abc import RichRenderable

from ..agent import AgentState
from ..message import UserMessage
from ..user_input import Command, CommandHandleOutput, UserInput


class CompactCommand(Command):
    def get_name(self) -> str:
        return 'compact'

    def get_command_desc(self) -> str:
        return 'Clear conversation history but keep a summary in context. Optional: /compact [instructions for summarization]'

    async def handle(self, agent_state: 'AgentState', user_input: UserInput) -> CommandHandleOutput:
        command_handle_output = await super().handle(agent_state, user_input)
        command_handle_output.user_msg.removed = True
        agent_state.session.append_message(command_handle_output.user_msg)
        await agent_state.session.compact_conversation_history(instructions=user_input.cleaned_input, show_status=True, llm_manager=agent_state.llm_manager)
        return command_handle_output

    def render_user_msg_suffix(self, user_msg: UserMessage) -> Generator[RichRenderable, None, None]:
        yield ''
