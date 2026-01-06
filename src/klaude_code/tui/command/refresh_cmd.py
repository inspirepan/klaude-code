from klaude_code.core.loaded_skills import get_loaded_skill_names_by_location
from klaude_code.protocol import commands, events, message

from .command_abc import Agent, CommandABC, CommandResult


class RefreshTerminalCommand(CommandABC):
    """Refresh terminal display"""

    @property
    def name(self) -> commands.CommandName:
        return commands.CommandName.REFRESH_TERMINAL

    @property
    def summary(self) -> str:
        return "Refresh terminal display"

    @property
    def is_interactive(self) -> bool:
        return True

    async def run(self, agent: Agent, user_input: message.UserInputPayload) -> CommandResult:
        del user_input  # unused
        import os

        os.system("cls" if os.name == "nt" else "clear")

        return CommandResult(
            events=[
                events.WelcomeEvent(
                    session_id=agent.session.id,
                    work_dir=str(agent.session.work_dir),
                    llm_config=agent.get_llm_client().get_llm_config(),
                    loaded_skills=get_loaded_skill_names_by_location(),
                ),
                events.ReplayHistoryEvent(
                    session_id=agent.session.id,
                    events=list(agent.session.get_history_item()),
                    updated_at=agent.session.updated_at,
                    is_load=False,
                ),
            ],
        )
