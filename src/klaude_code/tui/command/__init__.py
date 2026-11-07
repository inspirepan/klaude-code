import importlib

from .command_abc import CommandABC, CommandResult
from .registry import (
    dispatch_command,
    get_command_info_list,
    get_command_names,
    get_commands,
    has_background_command,
    has_interactive_command,
    is_exit_command,
    is_registered_command,
    is_slash_command_name,
    register,
)
from .types import CommandInfo, CommandName

_COMMAND_MODULES: dict[str, str] = {
    "CopyCommand": "copy_cmd",
    "CompactCommand": "compact_cmd",
    "ForkSessionCommand": "fork_session_cmd",
    "RewindCommand": "rewind_cmd",
    "RefreshTerminalCommand": "refresh_cmd",
    "NewCommand": "new_cmd",
    "ModelCommand": "model_cmd",
    "ManageProvidersCommand": "manage_providers_cmd",
    "SubAgentModelCommand": "sub_agent_model_cmd",
    "StatusCommand": "status_cmd",
    "ContextCommand": "context_cmd",
    "LoginCommand": "login_cmd",
    "LogoutCommand": "logout_cmd",
    "ContinueCommand": "continue_cmd",
    "RecapCommand": "recap_cmd",
    "GrillMeCommand": "grill_me_cmd",
    "BtwCommand": "btw_cmd",
    "TasksCommand": "tasks_cmd",
    "StopCommand": "stop_cmd",
    "ExitCommand": "exit_cmd",
}
_commands_loaded = False


def ensure_commands_loaded() -> None:
    """Load all command instances before registering them in display order."""
    global _commands_loaded
    if _commands_loaded:
        return
    commands = [__getattr__(name)() for name in _COMMAND_MODULES]
    for command in commands:
        register(command)
    _commands_loaded = True


def __getattr__(name: str) -> type[CommandABC]:
    if name not in _COMMAND_MODULES:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = importlib.import_module(f".{_COMMAND_MODULES[name]}", __package__)
    command_class = getattr(module, name)
    if not isinstance(command_class, type) or not issubclass(command_class, CommandABC):
        raise TypeError(f"{module.__name__}.{name} must be a CommandABC subclass")
    return command_class


__all__ = [
    "CommandABC",
    "CommandInfo",
    "CommandName",
    "CommandResult",
    "dispatch_command",
    "ensure_commands_loaded",
    "get_command_info_list",
    "get_command_names",
    "get_commands",
    "has_background_command",
    "has_interactive_command",
    "is_exit_command",
    "is_registered_command",
    "is_slash_command_name",
]
