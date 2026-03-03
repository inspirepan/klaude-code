from klaude_code.app.log_viewer import start_log_viewer
from klaude_code.log import get_current_log_file, set_debug_logging
from klaude_code.protocol import events, message

from .command_abc import Agent, CommandABC, CommandResult
from .types import CommandName


class DebugCommand(CommandABC):
    """Enable debug mode."""

    @property
    def name(self) -> CommandName:
        return CommandName.DEBUG

    @property
    def summary(self) -> str:
        return "Enable debug mode"

    async def run(self, agent: Agent, user_input: message.UserInputPayload) -> CommandResult:
        del user_input  # unused
        set_debug_logging(True, write_to_file=True)
        log_file = get_current_log_file()
        assert log_file is not None
        viewer_url = start_log_viewer(log_file)
        return self._command_output(agent, f"Log file: {log_file}\nLog viewer: {viewer_url}")

    def _command_output(self, agent: "Agent", content: str, *, is_error: bool = False) -> CommandResult:
        return CommandResult(
            events=[
                events.NoticeEvent(
                    session_id=agent.session.id,
                    content=content,
                    is_error=is_error,
                )
            ]
        )
