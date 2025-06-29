from typing import TYPE_CHECKING, Generator

from rich.abc import RichRenderable

from ..message import UserMessage
from ..tui import render_suffix
from ..user_input import Command, CommandHandleOutput, UserInput

if TYPE_CHECKING:
    from ..agent import Agent


class ClearCommand(Command):
    def get_name(self) -> str:
        return 'clear'

    def get_command_desc(self) -> str:
        return 'Clear conversation history and free up context'

    async def handle(self, agent: 'Agent', user_input: UserInput) -> CommandHandleOutput:
        command_handle_output = await super().handle(agent, user_input)
        command_handle_output.user_msg.removed = True
        command_handle_output.user_msg.set_extra_data('cleared', True)
        agent.session.clear_conversation_history()
        return command_handle_output

    def render_user_msg_suffix(self, user_msg: UserMessage) -> Generator[RichRenderable, None, None]:
        if user_msg.get_extra_data('cleared', False):
            yield render_suffix('Conversation history cleared, context freed up')
