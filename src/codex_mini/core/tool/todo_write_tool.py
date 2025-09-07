from pydantic import BaseModel

from codex_mini.core.tool.tool_abc import ToolABC
from codex_mini.core.tool.tool_context import current_session_var
from codex_mini.core.tool.tool_registry import register
from codex_mini.protocol.llm_parameter import ToolSchema
from codex_mini.protocol.model import TodoItem, TodoUIExtra, ToolResultItem, todo_list_str
from codex_mini.protocol.tools import TODO_WRITE_TOOL_NAME


def get_new_completed_todos(old_todos: list[TodoItem], new_todos: list[TodoItem]) -> list[str]:
    """
    Compare old and new todo lists to find newly completed todos.

    Args:
        old_todos: Previous todo list from session
        new_todos: New todo list being set

    Returns:
        List of TodoItem content that were just completed (status changed to 'completed')
    """
    # Create a mapping of old todos by content for quick lookup
    old_todos_map = {todo.content: todo for todo in old_todos}

    new_completed: list[str] = []
    for new_todo in new_todos:
        # Check if this todo exists in the old list
        old_todo = old_todos_map.get(new_todo.content)
        if new_todo.status != "completed":
            continue
        if old_todo is not None:
            # Todo existed before, check if status changed to completed
            if old_todo.status != "completed":
                new_completed.append(new_todo.content)
        else:
            # New completed todo
            new_completed.append(new_todo.content)
    return new_completed


class TodoWriteArguments(BaseModel):
    todos: list[TodoItem]


@register(TODO_WRITE_TOOL_NAME)
class TodoWriteTool(ToolABC):
    @classmethod
    def schema(cls) -> ToolSchema:
        return ToolSchema(
            name=TODO_WRITE_TOOL_NAME,
            type="function",
            description="Use this tool to create and manage a structured task list for your current coding session. This helps you track progress, organize complex tasks, and demonstrate thoroughness to the user.\n\nin doubt, use this tool. Being proactive with task management demonstrates attentiveness and ensures you complete all requirements successfully.",
            parameters={
                "type": "object",
                "properties": {
                    "todos": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "content": {"type": "string", "minLength": 1},
                                "status": {"type": "string", "enum": ["pending", "in_progress", "completed"]},
                                "activeForm": {"type": "string", "minLength": 1},
                            },
                            "required": ["content", "status", "activeForm"],
                            "additionalProperties": False,
                        },
                        "description": "The updated todo list",
                    }
                },
                "required": ["todos"],
                "additionalProperties": False,
            },
        )

    @classmethod
    async def call(cls, arguments: str) -> ToolResultItem:
        try:
            args = TodoWriteArguments.model_validate_json(arguments)
        except ValueError as e:
            return ToolResultItem(
                status="error",
                output=f"Invalid arguments: {e}",
            )

        # Get current session to store todos
        session = current_session_var.get()
        if session is None:
            return ToolResultItem(
                status="error",
                output="No active session found",
            )

        # Get current todos before updating (for comparison)

        # Find newly completed todos
        new_completed = get_new_completed_todos(session.todos, args.todos)

        # Store todos directly as TodoItem objects in session
        session.todos = args.todos

        ui_extra = TodoUIExtra(todos=args.todos, new_completed=new_completed)

        response = f"""Todos have been modified successfully. Ensure that you continue to use the todo list to track your progress. Please proceed with the current tasks if applicable

<system-reminder>
Your todo list has changed. DO NOT mention this explicitly to the user. Here are the latest contents of your todo list:

{todo_list_str(args.todos)}. Continue on with the tasks at hand if applicable.
</system-reminder>"""

        return ToolResultItem(
            status="success",
            output=response,
            ui_extra=ui_extra.model_dump_json(),
        )
