from __future__ import annotations

from klaude_code.protocol import message, model
from klaude_code.protocol.commands import CommandName

from .base import Event


class UserMessageEvent(Event):
    content: str
    images: list[message.ImageURLPart] | None = None


class DeveloperMessageEvent(Event):
    """DeveloperMessages are reminders in user messages or tool results."""

    item: message.DeveloperMessage


class TodoChangeEvent(Event):
    todos: list[model.TodoItem]


class CommandOutputEvent(Event):
    """Event for command output display. Not persisted to session history."""

    command_name: CommandName | str
    content: str = ""
    ui_extra: model.ToolResultUIExtra | None = None
    is_error: bool = False
