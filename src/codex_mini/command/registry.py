from typing import TYPE_CHECKING

from codex_mini.command.command_abc import CommandResult
from codex_mini.core.agent import Agent
from codex_mini.protocol.commands import CommandName
from codex_mini.protocol.events import DeveloperMessageEvent
from codex_mini.protocol.model import CommandOutput, DeveloperMessageItem

if TYPE_CHECKING:
    from .command_abc import CommandABC

_COMMANDS: dict[CommandName, "CommandABC"] = {}


def register_command(command: "CommandABC") -> None:
    """Register a command in the global registry."""
    _COMMANDS[command.name] = command


def get_commands() -> dict[CommandName, "CommandABC"]:
    """Get all registered commands."""
    return _COMMANDS.copy()


def get_command_names() -> list[CommandName]:
    """Get all registered command names for completion."""
    return list(_COMMANDS.keys())


def initialize_builtin_commands() -> None:
    """Initialize and register all built-in commands."""
    from .diff_cmd import DiffCommand
    from .help_cmd import HelpCommand
    from .init_cmd import InitCommand
    from .model_cmd import ModelCommand

    register_command(HelpCommand())
    register_command(ModelCommand())
    register_command(DiffCommand())
    register_command(InitCommand())


# Initialize built-in commands on module import
initialize_builtin_commands()


async def dispatch_command(raw: str, agent: Agent) -> CommandResult:
    # Detect command name
    if not raw.startswith("/"):
        return CommandResult(agent_input=raw)

    splits = raw.split(" ", maxsplit=1)
    command_name_raw = splits[0][1:]
    rest = " ".join(splits[1:]) if len(splits) > 1 else ""

    try:
        command_name = CommandName(command_name_raw)
    except ValueError:
        return CommandResult(agent_input=raw)

    if command_name not in _COMMANDS:
        return CommandResult(agent_input=raw)

    command = _COMMANDS[command_name]

    try:
        return await command.run(rest, agent)
    except Exception as e:
        return CommandResult(
            events=[
                DeveloperMessageEvent(
                    session_id=agent.session.id,
                    item=DeveloperMessageItem(
                        content=f"Command {command_name} error: [{e.__class__.__name__}] {str(e)}",
                        command_output=CommandOutput(command_name=command_name, is_error=True),
                    ),
                )
            ]
        )
