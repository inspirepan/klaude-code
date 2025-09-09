from typing import TYPE_CHECKING, TypeVar

from codex_mini.command.command_abc import CommandResult
from codex_mini.core.agent import Agent
from codex_mini.protocol.commands import CommandName
from codex_mini.protocol.events import DeveloperMessageEvent
from codex_mini.protocol.model import CommandOutput, DeveloperMessageItem

if TYPE_CHECKING:
    from .command_abc import CommandABC

_COMMANDS: dict[CommandName, "CommandABC"] = {}

T = TypeVar("T", bound="CommandABC")


def register_command(cls: type[T]) -> type[T]:
    """Decorator to register a command class in the global registry."""
    instance = cls()
    _COMMANDS[instance.name] = instance
    return cls


def get_commands() -> dict[CommandName, "CommandABC"]:
    """Get all registered commands."""
    return _COMMANDS.copy()


def get_command_names() -> list[CommandName]:
    """Get all registered command names for completion."""
    return list(_COMMANDS.keys())


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


def is_interactive_command(raw: str) -> bool:
    if not raw.startswith("/"):
        return False
    splits = raw.split(" ", maxsplit=1)
    command_name_raw = splits[0][1:]
    try:
        command_name = CommandName(command_name_raw)
    except ValueError:
        return False
    if command_name not in _COMMANDS:
        return False
    command = _COMMANDS[command_name]
    return command.is_interactive
