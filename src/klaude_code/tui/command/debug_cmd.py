from klaude_code.log import DebugType, get_current_log_file, is_debug_enabled, set_debug_logging
from klaude_code.protocol import commands, events, message

from .command_abc import Agent, CommandABC, CommandResult


def _format_status() -> str:
    """Format the current debug status for display."""
    if not is_debug_enabled():
        return "Debug: OFF"

    log_file = get_current_log_file()
    log_path_str = str(log_file) if log_file else "(console)"
    return f"Debug: ON\nLog file: {log_path_str}"


def _parse_debug_filters(raw: str) -> set[DebugType] | None:
    filters: set[DebugType] = set()
    for chunk in raw.split(","):
        normalized = chunk.strip().lower().replace("-", "_")
        if not normalized:
            continue
        try:
            filters.add(DebugType(normalized))
        except ValueError as exc:
            raise ValueError(normalized) from exc
    return filters or None


class DebugCommand(CommandABC):
    """Toggle debug mode and configure debug filters."""

    @property
    def name(self) -> commands.CommandName:
        return commands.CommandName.DEBUG

    @property
    def summary(self) -> str:
        return "Toggle debug mode (optional: filter types)"

    @property
    def support_addition_params(self) -> bool:
        return True

    @property
    def placeholder(self) -> str:
        return "filter types"

    async def run(self, agent: Agent, user_input: message.UserInputPayload) -> CommandResult:
        raw = user_input.text.strip()

        # /debug (no args) - enable debug
        if not raw:
            set_debug_logging(True, write_to_file=True)
            return self._command_output(agent, _format_status())

        # /debug <filters> - enable with filters
        try:
            filters = _parse_debug_filters(raw)
            if filters:
                set_debug_logging(True, write_to_file=True, filters=filters)
                filter_names = ", ".join(sorted(dt.value for dt in filters))
                return self._command_output(agent, f"Filters: {filter_names}\n{_format_status()}")
        except ValueError:
            pass

        return self._command_output(
            agent, f"Invalid filter: {raw}\nValid: {', '.join(dt.value for dt in DebugType)}", is_error=True
        )

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
