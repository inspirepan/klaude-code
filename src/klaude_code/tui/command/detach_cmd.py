from klaude_code.protocol import message

from .command_abc import Agent, CommandABC, CommandResult
from .types import CommandName


class DetachCommand(CommandABC):
    @property
    def name(self) -> CommandName:
        return CommandName.DETACH

    @property
    def summary(self) -> str:
        return "Exit the TUI without stopping running tasks"

    async def run(self, agent: Agent, user_input: message.UserInputPayload) -> CommandResult:
        # The runner handles detach before busy-time queueing or dispatch.
        return CommandResult()
