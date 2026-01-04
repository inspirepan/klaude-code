import asyncio

from klaude_code.protocol import commands, events, message, op

from .command_abc import Agent, CommandABC, CommandResult
from .model_picker import ModelSelectStatus, select_model_interactive


class ModelCommand(CommandABC):
    """Display or change the model configuration."""

    @property
    def name(self) -> commands.CommandName:
        return commands.CommandName.MODEL

    @property
    def summary(self) -> str:
        return "Change model (saves to config)"

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
        model_result = await asyncio.to_thread(select_model_interactive, preferred=user_input.text)

        current_model = agent.session.model_config_name
        selected_model = model_result.model if model_result.status == ModelSelectStatus.SELECTED else None
        if selected_model is None or selected_model == current_model:
            return CommandResult(
                events=[
                    events.CommandOutputEvent(
                        session_id=agent.session.id,
                        command_name=self.name,
                        content="(no change)",
                    )
                ]
            )
        return CommandResult(
            operations=[
                op.ChangeModelOperation(
                    session_id=agent.session.id,
                    model_name=selected_model,
                    save_as_default=True,
                )
            ]
        )
