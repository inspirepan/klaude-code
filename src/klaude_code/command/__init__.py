from .clear_cmd import ClearCommand
from .command_abc import CommandABC, CommandResult, InputAction, InputActionType
from .diff_cmd import DiffCommand
from .export_cmd import ExportCommand
from .help_cmd import HelpCommand

# InitCommand is now dynamically loaded via prompt_init.md
# from .init_cmd import InitCommand
from .model_cmd import ModelCommand
from .refresh_cmd import RefreshTerminalCommand
from .registry import (
    dispatch_command,
    get_commands,
    has_interactive_command,
    is_slash_command_name,
    load_prompt_commands,
    register_command,
)
from .status_cmd import StatusCommand
from .terminal_setup_cmd import TerminalSetupCommand

# Dynamically load prompt commands
load_prompt_commands()

__all__ = [
    "ClearCommand",
    "DiffCommand",
    "HelpCommand",
    "ModelCommand",
    "ExportCommand",
    "RefreshTerminalCommand",
    "StatusCommand",
    "TerminalSetupCommand",
    "register_command",
    "CommandABC",
    "CommandResult",
    "InputAction",
    "InputActionType",
    "dispatch_command",
    "get_commands",
    "is_slash_command_name",
    "has_interactive_command",
]
