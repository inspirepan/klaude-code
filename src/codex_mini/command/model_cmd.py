import asyncio

from codex_mini.command.command_abc import CommandABC, CommandResult
from codex_mini.command.registry import register_command
from codex_mini.config import load_config
from codex_mini.config.select_model import select_model_from_config
from codex_mini.core import Agent
from codex_mini.llm.registry import create_llm_client
from codex_mini.protocol.commands import CommandName
from codex_mini.protocol.events import DeveloperMessageEvent, WelcomeEvent
from codex_mini.protocol.model import CommandOutput, DeveloperMessageItem
from codex_mini.trace.log import log_debug


@register_command
class ModelCommand(CommandABC):
    """Display or change the model configuration."""

    @property
    def name(self) -> CommandName:
        return CommandName.MODEL

    @property
    def summary(self) -> str:
        return "select and switch LLM"

    @property
    def is_interactive(self) -> bool:
        return True

    async def run(self, raw: str, agent: Agent) -> CommandResult:
        selected_model = await asyncio.to_thread(select_model_from_config, preferred=raw)

        if selected_model is None or selected_model == agent.session.model_name:
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
        llm_config = config.get_model_config(selected_model)

        if agent.debug_mode:
            log_debug("▷▷▷ llm [Model Config]", llm_config.model_dump_json(exclude_none=True), style="yellow")

        llm_client = create_llm_client(llm_config)
        agent.set_llm_client(llm_client)

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
