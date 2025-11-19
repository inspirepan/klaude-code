from codex_mini.command.command_abc import CommandABC, CommandResult
from codex_mini.command.registry import register_command
from codex_mini.core import Agent
from codex_mini.protocol.commands import CommandName
from codex_mini.protocol.events import DeveloperMessageEvent
from codex_mini.protocol.model import CommandOutput, DeveloperMessageItem


@register_command
class HelpCommand(CommandABC):
    """Display help information for all available slash commands."""

    @property
    def name(self) -> CommandName:
        return CommandName.HELP

    @property
    def summary(self) -> str:
        return "Show help and available commands"

    async def run(self, raw: str, agent: Agent) -> CommandResult:
        lines: list[str] = [
            """
Usage:
  [b]@[/b] to mention file
  [b]esc[/b] to interrupt agent task
  [b]shift-enter[/b] or [b]ctrl-j[/b] for new line
  [b]--continue[/b] or [b]--resume[/b] to continue an old session
  [b]--select-model[/b] to switch model

Available slash commands:"""
        ]

        # Import here to avoid circular dependency
        from .registry import get_commands

        commands = get_commands()

        if commands:
            for cmd_name, cmd_obj in sorted(commands.items()):
                additional_instructions = " \\[additional instructions]" if cmd_obj.support_addition_params else ""
                lines.append(f"  [b]/{cmd_name}[/b]{additional_instructions} — {cmd_obj.summary}")

        event = DeveloperMessageEvent(
            session_id=agent.session.id,
            item=DeveloperMessageItem(content="\n".join(lines), command_output=CommandOutput(command_name=self.name)),
        )

        return CommandResult(events=[event])
