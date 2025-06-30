from typing import TYPE_CHECKING, Generator

from rich.abc import RichRenderable

from ..message import UserMessage
from ..tui import console
from ..user_input import Command, CommandHandleOutput, UserInput

if TYPE_CHECKING:
    from ..agent import Agent


class CompactCommand(Command):
    def get_name(self) -> str:
        return 'compact'

    def get_command_desc(self) -> str:
        return 'Clear conversation history but keep a summary in context. Optional: /compact [instructions for summarization]'

    async def handle(self, agent: 'Agent', user_input: UserInput) -> CommandHandleOutput:
        command_handle_output = await super().handle(agent, user_input)
        command_handle_output.user_msg.removed = True
        console.print()
        agent.session.append_message(command_handle_output.user_msg)
        await agent.session.compact_conversation_history(instructions=user_input.cleaned_input, show_status=True, llm_manager=agent.llm_manager)
        return command_handle_output

    def render_user_msg_suffix(self, user_msg: UserMessage) -> Generator[RichRenderable, None, None]:
        yield ''
