import asyncio

from klaude_code.command.command_abc import CommandABC, CommandResult
from klaude_code.command.registry import register_command
from klaude_code.config import load_config, select_model_from_config
from klaude_code.core import Agent
from klaude_code.llm import create_llm_client
from klaude_code.protocol import commands, events, model
from klaude_code.trace import DebugType, log_debug


@register_command
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

        config = load_config()
        assert config is not None
        llm_config = config.get_model_config(selected_model)

        log_debug(
            "Updated LLM config",
            llm_config.model_dump_json(exclude_none=True),
            style="yellow",
            debug_type=DebugType.LLM_CONFIG,
        )

        llm_client = create_llm_client(llm_config)
        agent.set_model_profile(agent.build_model_profile(llm_client))

        return CommandResult(
            events=[
                events.DeveloperMessageEvent(
                    session_id=agent.session.id,
                    item=model.DeveloperMessageItem(
                        content=f"switched to model: {selected_model}",
                        command_output=model.CommandOutput(command_name=self.name),
                    ),
                ),
                events.WelcomeEvent(llm_config=llm_config, work_dir=str(agent.session.work_dir)),
            ]
        )
