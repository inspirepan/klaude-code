from klaude_code.protocol import commands, message, op

from .command_abc import Agent, CommandABC, CommandResult


class NewCommand(CommandABC):
    """Start a new conversation in a fresh session."""

    @property
    def name(self) -> commands.CommandName:
        return commands.CommandName.NEW

    @property
    def summary(self) -> str:
        return "Start a new session"

    async def run(self, agent: Agent, user_input: message.UserInputPayload) -> CommandResult:
        del user_input  # unused
        import os

        os.system("cls" if os.name == "nt" else "clear")

        return CommandResult(
            operations=[op.ClearSessionOperation(session_id=agent.session.id)],
        )
