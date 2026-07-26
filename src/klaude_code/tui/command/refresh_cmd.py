from klaude_code.protocol import events, message

from .command_abc import Agent, CommandABC, CommandResult
from .types import CommandName


class RefreshTerminalCommand(CommandABC):
    """Refresh terminal display"""

    @property
    def name(self) -> CommandName:
        return CommandName.REFRESH_TERMINAL

    @property
    def summary(self) -> str:
        return "Refresh terminal display"

    @property
    def is_interactive(self) -> bool:
        return True

    async def run(self, agent: Agent, user_input: message.UserInputPayload) -> CommandResult:
        del user_input  # unused
        # The display clears the terminal and repaints the transcript from its
        # event tape — the same rebuild path Ctrl+O uses — so the banner and
        # any in-flight turn survive the refresh.
        return CommandResult(
            events=[events.RefreshDisplayEvent(session_id=agent.session.id)],
        )
