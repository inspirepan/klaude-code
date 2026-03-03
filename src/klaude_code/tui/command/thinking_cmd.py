from klaude_code.protocol import message, op

from .command_abc import Agent, CommandABC, CommandResult
from .types import CommandName


class ThinkingCommand(CommandABC):
    """Configure model thinking/reasoning level."""

    @property
    def name(self) -> CommandName:
        return CommandName.THINKING

    @property
    def summary(self) -> str:
        return "Change thinking level"

    @property
    def is_interactive(self) -> bool:
        return True

    async def run(self, agent: Agent, user_input: message.UserInputPayload) -> CommandResult:
        del user_input  # unused
        return CommandResult(operations=[op.RequestThinkingOperation(session_id=agent.session.id)])
