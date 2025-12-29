from .command_abc import CommandABC, CommandResult
from .registry import (
    dispatch_command,
    get_command_info_list,
    get_command_names,
    get_commands,
    has_interactive_command,
    is_slash_command_name,
    load_prompt_commands,
    register,
)

# Lazy load commands to avoid heavy imports at module load time
_commands_loaded = False


def ensure_commands_loaded() -> None:
    """Ensure all commands are loaded (lazy initialization).

    This function is called internally by registry functions like get_commands(),
    dispatch_command(), etc. It can also be called explicitly if early loading is desired.

    Commands are registered in display order - the order here determines
    the order shown in slash command completion.
    """
    global _commands_loaded
    if _commands_loaded:
        return
    _commands_loaded = True

    # Import and register commands in display order
    from .clear_cmd import ClearCommand
    from .debug_cmd import DebugCommand
    from .export_cmd import ExportCommand
    from .export_online_cmd import ExportOnlineCommand
    from .fork_session_cmd import ForkSessionCommand
    from .help_cmd import HelpCommand
    from .model_cmd import ModelCommand
    from .refresh_cmd import RefreshTerminalCommand
    from .release_notes_cmd import ReleaseNotesCommand
    from .resume_cmd import ResumeCommand
    from .status_cmd import StatusCommand
    from .terminal_setup_cmd import TerminalSetupCommand
    from .thinking_cmd import ThinkingCommand

    # Register in desired display order
    register(ExportCommand())
    register(ExportOnlineCommand())
    register(RefreshTerminalCommand())
    register(ThinkingCommand())
    register(ModelCommand())
    register(ForkSessionCommand())
    register(ResumeCommand())
    load_prompt_commands()
    register(StatusCommand())
    register(HelpCommand())
    register(ReleaseNotesCommand())
    register(TerminalSetupCommand())
    register(DebugCommand())
    register(ClearCommand())

    # Load prompt-based commands (appended after built-in commands)


# Lazy accessors for command classes
def __getattr__(name: str) -> object:
    _commands_map = {
        "ClearCommand": "clear_cmd",
        "DebugCommand": "debug_cmd",
        "ExportCommand": "export_cmd",
        "ExportOnlineCommand": "export_online_cmd",
        "ForkSessionCommand": "fork_session_cmd",
        "HelpCommand": "help_cmd",
        "ModelCommand": "model_cmd",
        "RefreshTerminalCommand": "refresh_cmd",
        "ReleaseNotesCommand": "release_notes_cmd",
        "ResumeCommand": "resume_cmd",
        "StatusCommand": "status_cmd",
        "TerminalSetupCommand": "terminal_setup_cmd",
        "ThinkingCommand": "thinking_cmd",
    }
    if name in _commands_map:
        import importlib

        module = importlib.import_module(f".{_commands_map[name]}", __package__)
        return getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    # Command classes are lazily loaded via __getattr__
    # "ClearCommand", "DiffCommand", "HelpCommand", "ModelCommand",
    # "ExportCommand", "RefreshTerminalCommand", "ReleaseNotesCommand",
    # "StatusCommand", "TerminalSetupCommand",
    "CommandABC",
    "CommandResult",
    "dispatch_command",
    "ensure_commands_loaded",
    "get_command_info_list",
    "get_command_names",
    "get_commands",
    "has_interactive_command",
    "is_slash_command_name",
]
