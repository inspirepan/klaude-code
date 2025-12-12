import asyncio

from klaude_code.command.command_abc import Agent, CommandABC, CommandResult, InputAction
from klaude_code.config.select_model import select_model_from_config
from klaude_code.protocol import commands, events, model


class ModelCommand(CommandABC):
    """Display or change the model configuration."""

    @property
    def name(self) -> commands.CommandName:
        return commands.CommandName.MODEL

    @property
    def summary(self) -> str:
        return "Select and switch LLM"

    @property
    def is_interactive(self) -> bool:
        return True

    @property
    def support_addition_params(self) -> bool:
        return True

    @property
    def placeholder(self) -> str:
        return "model name"

    async def run(self, raw: str, agent: Agent) -> CommandResult:
        selected_model = await asyncio.to_thread(select_model_from_config, preferred=raw)

        current_model = agent.profile.llm_client.model_name if agent.profile else None
        if selected_model is None or selected_model == current_model:
            return CommandResult(
                events=[
                    events.DeveloperMessageEvent(
                        session_id=agent.session.id,
                        item=model.DeveloperMessageItem(
                            content="(no change)",
                            command_output=model.CommandOutput(command_name=self.name),
                        ),
                    )
                ]
            )

        return CommandResult(actions=[InputAction.change_model(selected_model)])
