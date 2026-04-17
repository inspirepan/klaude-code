from klaude_code.protocol import message, op
from klaude_code.tui.command.command_abc import Agent, CommandABC, CommandResult
from klaude_code.tui.command.types import CommandName


class RecapCommand(CommandABC):
    @property
    def name(self) -> CommandName:
        return CommandName.RECAP

    @property
    def summary(self) -> str:
        return "Generate a 'while you were away' recap for the current session"

    async def run(self, agent: Agent, user_input: message.UserInputPayload) -> CommandResult:
        del user_input
        return CommandResult(
            operations=[
                op.GenerateAwaySummaryOperation(
                    session_id=agent.session.id,
                    source="manual",
                )
            ]
        )
