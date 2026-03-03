from klaude_code.protocol import message, op

from .command_abc import Agent, CommandABC, CommandResult
from .types import CommandName


class ModelCommand(CommandABC):
    """Display or change the model configuration."""

    @property
    def name(self) -> CommandName:
        return CommandName.MODEL

    @property
    def summary(self) -> str:
        return "Configure default model"

    @property
    def is_interactive(self) -> bool:
        return True

    @property
    def support_addition_params(self) -> bool:
        return True

    @property
    def placeholder(self) -> str:
        return "model name"

    async def run(self, agent: Agent, user_input: message.UserInputPayload) -> CommandResult:
        preferred = user_input.text.strip() or None
        return CommandResult(
            operations=[
                op.RequestModelOperation(
                    session_id=agent.session.id,
                    preferred=preferred,
                    save_as_default=True,
                )
            ]
        )
