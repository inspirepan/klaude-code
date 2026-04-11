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
        initial_search_text = user_input.text.strip() or None
        return CommandResult(
            operations=[
                op.RequestModelOperation(
                    session_id=agent.session.id,
                    initial_search_text=initial_search_text,
                    save_as_default=True,
                )
            ]
        )
