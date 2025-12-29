from klaude_code.command.command_abc import Agent, CommandABC, CommandResult
from klaude_code.protocol import commands, events, model


class HelpCommand(CommandABC):
    """Display help information for all available slash commands."""

    @property
    def name(self) -> commands.CommandName:
        return commands.CommandName.HELP

    @property
    def summary(self) -> str:
        return "Show help and available commands"

    async def run(self, agent: Agent, user_input: model.UserInputPayload) -> CommandResult:
        del user_input  # unused
        lines: list[str] = [
            """
Usage:
  [b]@[/b] to mention file
  [b]esc[/b] to interrupt agent task
  [b]shift-enter[/b] or [b]ctrl-j[/b] for new line
  [b]ctrl-v[/b] for pasting image
  [b]ctrl-l[/b] to switch model
  [b]ctrl-t[/b] to switch thinking level
  [b]--continue[/b] or [b]--resume[/b] to continue an old session

Available slash commands:"""
        ]

        # Import here to avoid circular dependency
        from .registry import get_commands

        commands = get_commands()

        if commands:
            for cmd_name, cmd_obj in sorted(commands.items()):
                placeholder = f" \\[{cmd_obj.placeholder}]" if cmd_obj.support_addition_params else ""
                lines.append(f"  [b]/{cmd_name}[/b]{placeholder} — {cmd_obj.summary}")

        event = events.DeveloperMessageEvent(
            session_id=agent.session.id,
            item=model.DeveloperMessageItem(
                content="\n".join(lines),
                command_output=model.CommandOutput(command_name=self.name),
            ),
        )

        return CommandResult(events=[event])
