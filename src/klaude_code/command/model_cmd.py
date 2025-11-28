import asyncio

from klaude_code.command.command_abc import CommandABC, CommandResult
from klaude_code.command.registry import register_command
from klaude_code.config import load_config
from klaude_code.config.select_model import select_model_from_config
from klaude_code.core import Agent
from klaude_code.llm.registry import create_llm_client
from klaude_code.protocol.commands import CommandName
from klaude_code.protocol.events import DeveloperMessageEvent, WelcomeEvent
from klaude_code.protocol.model import CommandOutput, DeveloperMessageItem
from klaude_code.trace import DebugType, log_debug


@register_command
class ModelCommand(CommandABC):
    """Display or change the model configuration."""

    @property
    def name(self) -> CommandName:
        return CommandName.MODEL

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
                    DeveloperMessageEvent(
                        session_id=agent.session.id,
                        item=DeveloperMessageItem(
                            content="(no change)", command_output=CommandOutput(command_name=self.name)
                        ),
                    )
                ]
            )

        config = load_config()
        assert config is not None
        llm_config = config.get_model_config(selected_model)

        log_debug(
            "Updated model config",
            llm_config.model_dump_json(exclude_none=True),
            style="yellow",
            debug_type=DebugType.LLM_CONFIG,
        )

        llm_client = create_llm_client(llm_config)
        agent.set_model_profile(agent.build_model_profile(llm_client))

        return CommandResult(
            events=[
                DeveloperMessageEvent(
                    session_id=agent.session.id,
                    item=DeveloperMessageItem(
                        content=f"switched to model: {selected_model}",
                        command_output=CommandOutput(command_name=self.name),
                    ),
                ),
                WelcomeEvent(llm_config=llm_config, work_dir=str(agent.session.work_dir)),
            ]
        )
