from klaude_code.protocol import message, op
from klaude_code.tui.command.command_abc import Agent, CommandABC, CommandResult
from klaude_code.tui.command.types import CommandName


class BtwCommand(CommandABC):
    """Ask a question on the side without touching the running task."""

    @property
    def name(self) -> CommandName:
        return CommandName.BTW

    @property
    def summary(self) -> str:
        return "Ask a side question about the current context, without disturbing the task"

    @property
    def support_addition_params(self) -> bool:
        return True

    @property
    def placeholder(self) -> str:
        return "question"

    @property
    def runs_in_background(self) -> bool:
        return True

    async def run(self, agent: Agent, user_input: message.UserInputPayload) -> CommandResult:
        return CommandResult(
            operations=[
                op.AskSideQuestionOperation(
                    session_id=agent.session.id,
                    question=user_input.text,
                )
            ]
        )
