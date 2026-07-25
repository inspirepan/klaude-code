from klaude_code.protocol import message, op

from .command_abc import Agent, CommandABC, CommandResult
from .types import CommandName


class ContextCommand(CommandABC):
    """Display estimated context-window usage by category."""

    @property
    def name(self) -> CommandName:
        return CommandName.CONTEXT

    @property
    def summary(self) -> str:
        return "Show context window usage"

    async def run(self, agent: Agent, user_input: message.UserInputPayload) -> CommandResult:
        del user_input  # unused
        return CommandResult(operations=[op.GetContextUsageOperation(session_id=agent.session.id)])
