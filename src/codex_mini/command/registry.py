from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .command_abc import CommandABC

_COMMANDS: dict[str, "CommandABC"] = {}


def register_command(command: "CommandABC") -> None:
    """Register a command in the global registry."""
    _COMMANDS[command.name] = command


def get_commands() -> dict[str, "CommandABC"]:
    """Get all registered commands."""
    return _COMMANDS.copy()


def get_command_names() -> list[str]:
    """Get all registered command names for completion."""
    return list(_COMMANDS.keys())


def initialize_builtin_commands() -> None:
    """Initialize and register all built-in commands."""
    from .diff_cmd import DiffCommand
    from .help_cmd import HelpCommand
    from .model_cmd import ModelCommand

    register_command(HelpCommand())
    register_command(ModelCommand())
    register_command(DiffCommand())


# Initialize built-in commands on module import
initialize_builtin_commands()
