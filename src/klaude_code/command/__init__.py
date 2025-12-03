from .command_abc import CommandABC, CommandResult, InputAction, InputActionType
from .registry import (
    dispatch_command,
    get_commands,
    has_interactive_command,
    is_slash_command_name,
    load_prompt_commands,
    register_command,
)

# Lazy load commands to avoid heavy imports at module load time
_commands_loaded = False


def ensure_commands_loaded() -> None:
    """Ensure all commands are loaded (lazy initialization).

    This function is called internally by registry functions like get_commands(),
    dispatch_command(), etc. It can also be called explicitly if early loading is desired.
    """
    global _commands_loaded
    if _commands_loaded:
        return
    _commands_loaded = True

    # Import command modules to trigger @register_command decorators
    from . import clear_cmd as _clear_cmd  # noqa: F401
    from . import diff_cmd as _diff_cmd  # noqa: F401
    from . import export_cmd as _export_cmd  # noqa: F401
    from . import help_cmd as _help_cmd  # noqa: F401
    from . import model_cmd as _model_cmd  # noqa: F401
    from . import refresh_cmd as _refresh_cmd  # noqa: F401
    from . import release_notes_cmd as _release_notes_cmd  # noqa: F401
    from . import status_cmd as _status_cmd  # noqa: F401
    from . import terminal_setup_cmd as _terminal_setup_cmd  # noqa: F401

    # Suppress unused variable warnings
    _ = (
        _clear_cmd,
        _diff_cmd,
        _export_cmd,
        _help_cmd,
        _model_cmd,
        _refresh_cmd,
        _release_notes_cmd,
        _status_cmd,
        _terminal_setup_cmd,
    )

    # Load prompt-based commands
    load_prompt_commands()


# Lazy accessors for command classes
def __getattr__(name: str) -> object:
    _commands_map = {
        "ClearCommand": "clear_cmd",
        "DiffCommand": "diff_cmd",
        "ExportCommand": "export_cmd",
        "HelpCommand": "help_cmd",
        "ModelCommand": "model_cmd",
        "RefreshTerminalCommand": "refresh_cmd",
        "ReleaseNotesCommand": "release_notes_cmd",
        "StatusCommand": "status_cmd",
        "TerminalSetupCommand": "terminal_setup_cmd",
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
    "register_command",
    "CommandABC",
    "CommandResult",
    "InputAction",
    "InputActionType",
    "dispatch_command",
    "get_commands",
    "is_slash_command_name",
    "has_interactive_command",
    "ensure_commands_loaded",
]
