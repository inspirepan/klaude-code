from importlib.resources import files
from typing import TYPE_CHECKING

from klaude_code.command.command_abc import Agent, CommandResult, InputAction
from klaude_code.command.prompt_command import PromptCommand
from klaude_code.protocol import commands, events, model
from klaude_code.trace import log_debug

if TYPE_CHECKING:
    from .command_abc import CommandABC

_COMMANDS: dict[commands.CommandName | str, "CommandABC"] = {}


def register(cmd: "CommandABC") -> None:
    """Register a command instance. Order of registration determines display order."""
    _COMMANDS[cmd.name] = cmd


def load_prompt_commands():
    """Dynamically load prompt-based commands from the command directory."""
    try:
        command_files = files("klaude_code.command").iterdir()
        for file_path in command_files:
            name = file_path.name
            if (name.startswith("prompt_") or name.startswith("prompt-")) and name.endswith(".md"):
                cmd = PromptCommand(name)
                _COMMANDS[cmd.name] = cmd
    except OSError as e:
        log_debug(f"Failed to load prompt commands: {e}")


def _ensure_commands_loaded() -> None:
    """Ensure all commands are loaded (lazy initialization)."""
    from klaude_code.command import ensure_commands_loaded

    ensure_commands_loaded()


def get_commands() -> dict[commands.CommandName | str, "CommandABC"]:
    """Get all registered commands."""
    _ensure_commands_loaded()
    return _COMMANDS.copy()


def is_slash_command_name(name: str) -> bool:
    _ensure_commands_loaded()
    return name in _COMMANDS


async def dispatch_command(raw: str, agent: Agent) -> CommandResult:
    _ensure_commands_loaded()
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
                        content=f"Command {command_identifier} error: [{e.__class__.__name__}] {e!s}",
                        command_output=command_output,
                    ),
                )
            ]
        )


def has_interactive_command(raw: str) -> bool:
    _ensure_commands_loaded()
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
