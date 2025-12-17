from klaude_code.command.command_abc import Agent, CommandABC, CommandResult
from klaude_code.protocol import commands, events, model
from klaude_code.trace import DebugType, get_current_log_file, is_debug_enabled, set_debug_logging


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

    async def run(self, agent: Agent, user_input: model.UserInputPayload) -> CommandResult:
        raw = user_input.text.strip()

        # /debug (no args) - enable debug
        if not raw:
            set_debug_logging(True, write_to_file=True)
            return self._message_result(agent, _format_status())

        # /debug <filters> - enable with filters
        try:
            filters = _parse_debug_filters(raw)
            if filters:
                set_debug_logging(True, write_to_file=True, filters=filters)
                filter_names = ", ".join(sorted(dt.value for dt in filters))
                return self._message_result(agent, f"Filters: {filter_names}\n{_format_status()}")
        except ValueError:
            pass

        return self._message_result(agent, f"Invalid filter: {raw}\nValid: {', '.join(dt.value for dt in DebugType)}")

    def _message_result(self, agent: "Agent", content: str) -> CommandResult:
        return CommandResult(
            events=[
                events.DeveloperMessageEvent(
                    session_id=agent.session.id,
                    item=model.DeveloperMessageItem(
                        content=content,
                        command_output=model.CommandOutput(command_name=self.name),
                    ),
                )
            ]
        )
