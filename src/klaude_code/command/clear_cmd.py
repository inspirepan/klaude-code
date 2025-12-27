from klaude_code.command.command_abc import Agent, CommandABC, CommandResult
from klaude_code.protocol import commands, model, op


class ClearCommand(CommandABC):
    """Clear current session and start a new conversation"""

    @property
    def name(self) -> commands.CommandName:
        return commands.CommandName.CLEAR

    @property
    def summary(self) -> str:
        return "Clear conversation history and free up context"

    async def run(self, agent: Agent, user_input: model.UserInputPayload) -> CommandResult:
        del user_input  # unused
        return CommandResult(
            operations=[op.ClearSessionOperation(session_id=agent.session.id)],
            persist_user_input=False,
        )
