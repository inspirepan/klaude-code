from importlib.resources import files
from typing import TYPE_CHECKING

from klaude_code.command.command_abc import Agent, CommandResult
from klaude_code.command.prompt_command import PromptCommand
from klaude_code.protocol import commands, events, model, op
from klaude_code.trace import log_debug

if TYPE_CHECKING:
    from .command_abc import CommandABC

_COMMANDS: dict[commands.CommandName | str, "CommandABC"] = {}


def _command_key_to_str(key: commands.CommandName | str) -> str:
    if isinstance(key, commands.CommandName):
        return key.value
    return key


def _resolve_command_key(command_name_raw: str) -> commands.CommandName | str | None:
    """Resolve raw command token to a registered command key.

    Resolution order:
    1) Exact match
    2) Enum conversion (for standard commands)
    3) Prefix match (supports abbreviations like `exp` -> `export`)

    Prefix match rules:
    - If there's exactly one prefix match, use it.
    - If multiple matches exist and one command name is a prefix of all others,
      treat it as the base command and use it (e.g. `export` over `export-online`).
    - Otherwise, consider it ambiguous and return None.
    """

    if not command_name_raw:
        return None

    # Exact string match (works for both Enum and str keys because CommandName is a str Enum)
    if command_name_raw in _COMMANDS:
        return command_name_raw

    # Enum conversion for standard commands
    try:
        enum_key = commands.CommandName(command_name_raw)
    except ValueError:
        enum_key = None
    else:
        if enum_key in _COMMANDS:
            return enum_key

    # Prefix match across all registered names
    matching_keys: list[commands.CommandName | str] = []
    matching_names: list[str] = []
    for key in _COMMANDS:
        key_str = _command_key_to_str(key)
        if key_str.startswith(command_name_raw):
            matching_keys.append(key)
            matching_names.append(key_str)

    if len(matching_keys) == 1:
        return matching_keys[0]

    if len(matching_keys) > 1:
        # Prefer the base command when one is a prefix of all other matches.
        base_matches = [
            key
            for key, key_name in zip(matching_keys, matching_names, strict=True)
            if all(other.startswith(key_name) for other in matching_names if other != key_name)
        ]
        if len(base_matches) == 1:
            return base_matches[0]

    return None


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


def get_command_info_list() -> list[commands.CommandInfo]:
    """Get lightweight command metadata for UI purposes.

    Returns CommandInfo list in registration order (display order).
    """
    _ensure_commands_loaded()
    return [
        commands.CommandInfo(
            name=_command_key_to_str(cmd.name),
            summary=cmd.summary,
            support_addition_params=cmd.support_addition_params,
            placeholder=cmd.placeholder,
        )
        for cmd in _COMMANDS.values()
    ]


def get_command_names() -> frozenset[str]:
    """Get all registered command names as a frozen set for fast lookup."""
    _ensure_commands_loaded()
    return frozenset(_command_key_to_str(key) for key in _COMMANDS)


def is_slash_command_name(name: str) -> bool:
    _ensure_commands_loaded()
    return _resolve_command_key(name) is not None


async def dispatch_command(user_input: model.UserInputPayload, agent: Agent, *, submission_id: str) -> CommandResult:
    _ensure_commands_loaded()
    # Detect command name
    raw = user_input.text
    if not raw.startswith("/"):
        return CommandResult(
            operations=[
                op.RunAgentOperation(
                    id=submission_id,
                    session_id=agent.session.id,
                    input=user_input,
                )
            ]
        )

    splits = raw.split(" ", maxsplit=1)
    command_name_raw = splits[0][1:]
    rest = " ".join(splits[1:]) if len(splits) > 1 else ""

    command_key = _resolve_command_key(command_name_raw)
    if command_key is None:
        return CommandResult(
            operations=[
                op.RunAgentOperation(
                    id=submission_id,
                    session_id=agent.session.id,
                    input=user_input,
                )
            ]
        )

    command = _COMMANDS[command_key]
    command_identifier: commands.CommandName | str = command.name

    try:
        user_input_for_command = model.UserInputPayload(text=rest, images=user_input.images)
        result = await command.run(agent, user_input_for_command)
        ops = list(result.operations or [])
        for operation in ops:
            if isinstance(operation, op.RunAgentOperation):
                operation.id = submission_id
        if ops:
            result.operations = ops
        return result
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
    command_key = _resolve_command_key(command_name_raw)
    if command_key is None:
        return False
    command = _COMMANDS[command_key]
    return command.is_interactive
