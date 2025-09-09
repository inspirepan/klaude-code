from codex_mini.command.command_abc import CommandABC, CommandResult
from codex_mini.core import Agent
from codex_mini.protocol.commands import CommandName


class ModelCommand(CommandABC):
    """Display or change the model configuration."""

    @property
    def name(self) -> CommandName:
        return CommandName.MODEL

    @property
    def summary(self) -> str:
        return "select and switch LLM"

    async def run(self, raw: str, agent: Agent) -> CommandResult:
        # TODO
        return CommandResult(agent_input=raw)
