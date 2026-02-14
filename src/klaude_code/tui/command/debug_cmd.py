from klaude_code.log import get_current_log_file, is_debug_enabled, set_debug_logging
from klaude_code.protocol import commands, events, message

from .command_abc import Agent, CommandABC, CommandResult


def _format_status() -> str:
    """Format the current debug status for display."""
    if not is_debug_enabled():
        return "Debug: OFF"

    log_file = get_current_log_file()
    log_path_str = str(log_file) if log_file else "(console)"
    return f"Debug: ON\nLog file: {log_path_str}"


class DebugCommand(CommandABC):
    """Toggle debug mode."""

    @property
    def name(self) -> commands.CommandName:
        return commands.CommandName.DEBUG

    @property
    def summary(self) -> str:
        return "Toggle debug mode"

    async def run(self, agent: Agent, user_input: message.UserInputPayload) -> CommandResult:
        set_debug_logging(True, write_to_file=True)
        return self._command_output(agent, _format_status())

    def _command_output(self, agent: "Agent", content: str, *, is_error: bool = False) -> CommandResult:
        return CommandResult(
            events=[
                events.CommandOutputEvent(
                    session_id=agent.session.id,
                    command_name=self.name,
                    content=content,
                    is_error=is_error,
                )
            ]
        )
