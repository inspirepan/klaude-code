from codex_mini.command.command_abc import CommandABC, CommandResult
from codex_mini.command.registry import register_command
from codex_mini.core import Agent
from codex_mini.protocol.commands import CommandName
from codex_mini.protocol.events import DeveloperMessageEvent
from codex_mini.protocol.model import CommandOutput, DeveloperMessageItem


@register_command
class PlanCommand(CommandABC):
    """Activate Plan Mode"""

    @property
    def name(self) -> CommandName:
        return CommandName.PLAN

    @property
    def support_addition_params(self) -> bool:
        return True

    @property
    def summary(self) -> str:
        return "run with plan mode"

    async def run(self, raw: str, agent: Agent) -> CommandResult:
        msg = agent.enter_plan_mode()

        return CommandResult(
            agent_input=raw.strip(),
            events=[
                DeveloperMessageEvent(
                    session_id=agent.session.id,
                    item=DeveloperMessageItem(
                        content="started new conversation",
                        command_output=CommandOutput(command_name=self.name, ui_extra=msg),
                    ),
                ),
            ],
        )
