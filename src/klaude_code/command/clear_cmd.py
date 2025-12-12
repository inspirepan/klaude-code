from klaude_code.command.command_abc import Agent, CommandABC, CommandResult, InputAction
from klaude_code.protocol import commands


class ClearCommand(CommandABC):
    """Clear current session and start a new conversation"""

    @property
    def name(self) -> commands.CommandName:
        return commands.CommandName.CLEAR

    @property
    def summary(self) -> str:
        return "Clear conversation history and free up context"

    async def run(self, raw: str, agent: Agent) -> CommandResult:
        return CommandResult(actions=[InputAction.clear()])
