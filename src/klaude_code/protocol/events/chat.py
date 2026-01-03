from __future__ import annotations

from klaude_code.protocol import message, model

from .base import Event


class UserMessageEvent(Event):
    content: str
    images: list[message.ImageURLPart] | None = None


class DeveloperMessageEvent(Event):
    """DeveloperMessages are reminders in user messages or tool results."""

    item: message.DeveloperMessage


class TodoChangeEvent(Event):
    todos: list[model.TodoItem]
