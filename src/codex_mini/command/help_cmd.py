from typing import Any

from codex_mini.command.command_abc import CommandABC
from codex_mini.protocol.events import DeveloperMessageEvent, Event
from codex_mini.protocol.model import DeveloperMessageItem


class HelpCommand(CommandABC):
    """Display help information for all available slash commands."""

    @property
    def name(self) -> str:
        return "help"

    @property
    def summary(self) -> str:
        return "Show help and available commands"

    async def run(self, raw: str, session_id: str | None) -> tuple[dict[str, Any] | None, list[Event]]:
        # Import here to avoid circular dependency
        from .registry import get_commands

        commands = get_commands()

        if not commands:
            help_text = "No available slash commands."
        else:
            lines = ["Available slash commands:", ""]
            for cmd_name, cmd_obj in sorted(commands.items()):
                lines.append(f"  /{cmd_name} — {cmd_obj.summary}")
            help_text = "\n".join(lines)

        event = DeveloperMessageEvent(session_id=session_id or "default", item=DeveloperMessageItem(content=help_text))

        return None, [event]
