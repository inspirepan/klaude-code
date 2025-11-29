from importlib.resources import files
from typing import TYPE_CHECKING, TypeVar

from klaude_code.command.command_abc import CommandResult, InputAction
from klaude_code.command.prompt_command import PromptCommand
from klaude_code.core.agent import Agent
from klaude_code.protocol import commands, events, model

if TYPE_CHECKING:
    from .command_abc import CommandABC

_COMMANDS: dict[commands.CommandName | str, "CommandABC"] = {}

T = TypeVar("T", bound="CommandABC")


def register_command(cls: type[T]) -> type[T]:
    """Decorator to register a command class in the global registry."""
    instance = cls()
    _COMMANDS[instance.name] = instance
    return cls


def load_prompt_commands():
    """Dynamically load prompt-based commands from the command directory."""
    try:
        command_files = files("klaude_code.command").iterdir()
        for file_path in command_files:
            name = file_path.name
            if (name.startswith("prompt_") or name.startswith("prompt-")) and name.endswith(".md"):
                cmd = PromptCommand(name)
                _COMMANDS[cmd.name] = cmd
    except Exception:
        # If resource loading fails, just ignore
        pass


def get_commands() -> dict[commands.CommandName | str, "CommandABC"]:
    """Get all registered commands."""
    return _COMMANDS.copy()


def get_command_names() -> list[str]:
    """Get all registered command names for completion."""
    return [str(k) for k in _COMMANDS.keys()]


async def dispatch_command(raw: str, agent: Agent) -> CommandResult:
    # Detect command name
    if not raw.startswith("/"):
        return CommandResult(actions=[InputAction.run_agent(raw)])

    splits = raw.split(" ", maxsplit=1)
    command_name_raw = splits[0][1:]
    rest = " ".join(splits[1:]) if len(splits) > 1 else ""

    # Try to match against registered commands (both Enum and string keys)
    command_key = None

    # First try exact string match
    if command_name_raw in _COMMANDS:
        command_key = command_name_raw
    else:
        # Then try Enum conversion for standard commands
        try:
            enum_key = commands.CommandName(command_name_raw)
            if enum_key in _COMMANDS:
                command_key = enum_key
        except ValueError:
            pass

    if command_key is None:
        return CommandResult(actions=[InputAction.run_agent(raw)])

    command = _COMMANDS[command_key]
    command_identifier: commands.CommandName | str = command.name

    try:
        return await command.run(rest, agent)
    except Exception as e:
        command_output = (
            model.CommandOutput(command_name=command_identifier, is_error=True)
            if isinstance(command_identifier, commands.CommandName)
            else None
        )
        return CommandResult(
            events=[
                events.DeveloperMessageEvent(
                    session_id=agent.session.id,
                    item=model.DeveloperMessageItem(
                        content=f"Command {command_identifier} error: [{e.__class__.__name__}] {str(e)}",
                        command_output=command_output,
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
        command_name = commands.CommandName(command_name_raw)
    except ValueError:
        return False
    if command_name not in _COMMANDS:
        return False
    command = _COMMANDS[command_name]
    return command.is_interactive
