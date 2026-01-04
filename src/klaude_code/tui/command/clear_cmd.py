from klaude_code.protocol import commands, message, op

from .command_abc import Agent, CommandABC, CommandResult


class ClearCommand(CommandABC):
    """Clear current session and start a new conversation"""

    @property
    def name(self) -> commands.CommandName:
        return commands.CommandName.CLEAR

    @property
    def summary(self) -> str:
        return "Clear conversation history and free up context"

    async def run(self, agent: Agent, user_input: message.UserInputPayload) -> CommandResult:
        del user_input  # unused
        import os

        os.system("cls" if os.name == "nt" else "clear")

        return CommandResult(
            operations=[op.ClearSessionOperation(session_id=agent.session.id)],
        )
