"""Command for changing sub-agent models and compact model."""

from klaude_code.protocol import message, op

from .command_abc import Agent, CommandABC, CommandResult
from .types import CommandName


class SubAgentModelCommand(CommandABC):
    """Configure models for sub-agents and compact model."""

    @property
    def name(self) -> CommandName:
        return CommandName.SUB_AGENT_MODEL

    @property
    def summary(self) -> str:
        return "Configure default sub-agent models"

    @property
    def is_interactive(self) -> bool:
        return True

    async def run(self, agent: Agent, user_input: message.UserInputPayload) -> CommandResult:
        del user_input  # keep slash command no-arg only
        return CommandResult(
            operations=[op.RequestSubAgentModelOperation(session_id=agent.session.id, save_as_default=True)]
        )
