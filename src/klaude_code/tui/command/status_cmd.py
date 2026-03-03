from klaude_code.protocol import message, op

from .command_abc import Agent, CommandABC, CommandResult
from .types import CommandName


class StatusCommand(CommandABC):
    """Display session usage statistics."""

    @property
    def name(self) -> CommandName:
        return CommandName.STATUS

    @property
    def summary(self) -> str:
        return "Show session status"

    async def run(self, agent: Agent, user_input: message.UserInputPayload) -> CommandResult:
        del user_input  # unused
        return CommandResult(operations=[op.GetSessionStatusOperation(session_id=agent.session.id)])
