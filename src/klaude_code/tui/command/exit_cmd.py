from klaude_code.protocol import message

from .command_abc import Agent, CommandABC, CommandResult
from .types import CommandName


class ExitCommand(CommandABC):
    @property
    def name(self) -> CommandName:
        return CommandName.EXIT

    @property
    def summary(self) -> str:
        return "Exit Klaude, stopping owned tasks after confirmation"

    async def run(self, agent: Agent, user_input: message.UserInputPayload) -> CommandResult:
        # The runner handles exit before busy-time queueing or dispatch.
        return CommandResult()
