from pydantic import BaseModel

from klaude_code.protocol.models.common import TodoStatusType


class TodoItem(BaseModel):
    content: str
    status: TodoStatusType

def todo_list_str(todos: list[TodoItem]) -> str:
    return "[" + "\n".join(f"[{todo.status}] {todo.content}" for todo in todos) + "]\n"

__all__ = ["TodoItem", "todo_list_str"]