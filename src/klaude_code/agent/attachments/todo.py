from __future__ import annotations

from klaude_code.prompts.attachments import TODO_ITEMS_TEMPLATE, TODO_NUDGE_TEMPLATE
from klaude_code.protocol import message, tools
from klaude_code.protocol.models import DeveloperUIExtra, TodoAttachmentUIItem
from klaude_code.session import Session

TODO_ATTACHMENT_TURNS_SINCE_WRITE = 10
TODO_ATTACHMENT_TURNS_BETWEEN = 10


def _fmt_todo_items(todo_items_str: str) -> str:
    return TODO_ITEMS_TEMPLATE.format(todo_items_str=todo_items_str)


def _fmt_todo_nudge(todo_str: str) -> str:
    return TODO_NUDGE_TEMPLATE.format(todo_str=todo_str)


def _count_assistant_turns_since(session: Session) -> tuple[int, int]:
    turns_since_write = 0
    turns_since_attachment = 0
    found_write = False
    found_attachment = False

    for item in reversed(session.conversation_history):
        if isinstance(item, message.AssistantMessage):
            if not found_write:
                turns_since_write += 1
            if not found_attachment:
                turns_since_attachment += 1

        if not found_write and isinstance(item, message.ToolResultMessage) and item.tool_name == tools.TODO_WRITE:
            found_write = True

        if not found_attachment and isinstance(item, message.DeveloperMessage) and item.ui_extra:
            for ui_item in item.ui_extra.items:
                if isinstance(ui_item, TodoAttachmentUIItem):
                    found_attachment = True
                    break

        if found_write and found_attachment:
            break

    return turns_since_write, turns_since_attachment


async def todo_attachment(session: Session) -> message.DeveloperMessage | None:
    """Periodically attach a todo nudge if TodoWrite hasn't been used recently."""

    if not session.todos and not session.conversation_history:
        return None

    turns_since_write, turns_since_attachment = _count_assistant_turns_since(session)
    if turns_since_write < TODO_ATTACHMENT_TURNS_SINCE_WRITE:
        return None
    if turns_since_attachment < TODO_ATTACHMENT_TURNS_BETWEEN:
        return None

    todo_str = ""
    if session.todos:
        todo_items_str = "\n".join(
            f"{idx + 1}. [{todo.status}] {todo.content}" for idx, todo in enumerate(session.todos)
        )
        todo_str = _fmt_todo_items(todo_items_str)

    reason = TodoAttachmentUIItem(reason="not_used_recently" if session.todos else "empty")
    return message.DeveloperMessage(
        parts=message.text_parts_from_str(f"<system-reminder>{_fmt_todo_nudge(todo_str)}\n</system-reminder>"),
        ui_extra=DeveloperUIExtra(items=[reason]),
    )
