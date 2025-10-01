from codex_mini.command.command_abc import CommandABC, CommandResult
from codex_mini.command.registry import register_command
from codex_mini.core import Agent
from codex_mini.protocol import events
from codex_mini.protocol.commands import CommandName


@register_command
class RefreshTerminalCommand(CommandABC):
    """Refresh terminal display"""

    @property
    def name(self) -> CommandName:
        return CommandName.REFRESH_TERMINAL

    @property
    def summary(self) -> str:
        return "refresh terminal display"

    @property
    def is_interactive(self) -> bool:
        return True

    async def run(self, raw: str, agent: Agent) -> CommandResult:
        import os

        os.system("cls" if os.name == "nt" else "clear")

        result = CommandResult(
            events=[
                events.WelcomeEvent(
                    work_dir=str(agent.session.work_dir),
                    llm_config=agent.get_llm_client().get_llm_config(),
                ),
                events.ReplayHistoryEvent(
                    session_id=agent.session.id,
                    events=list(agent.session.get_history_item()),
                    updated_at=agent.session.updated_at,
                    is_load=False,
                ),
            ]
        )

        return result
