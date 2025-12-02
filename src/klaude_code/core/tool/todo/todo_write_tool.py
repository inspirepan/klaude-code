from pathlib import Path

from pydantic import BaseModel

from klaude_code.core.tool.tool_abc import ToolABC, load_desc
from klaude_code.core.tool.tool_context import get_current_todo_context
from klaude_code.core.tool.tool_registry import register
from klaude_code.protocol import llm_param, model, tools


def get_new_completed_todos(old_todos: list[model.TodoItem], new_todos: list[model.TodoItem]) -> list[str]:
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
    todos: list[model.TodoItem]


@register(tools.TODO_WRITE)
class TodoWriteTool(ToolABC):
    @classmethod
    def schema(cls) -> llm_param.ToolSchema:
        return llm_param.ToolSchema(
            name=tools.TODO_WRITE,
            type="function",
            description=load_desc(Path(__file__).parent / "todo_write_tool.md"),
            parameters={
                "type": "object",
                "properties": {
                    "todos": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "content": {"type": "string", "minLength": 1},
                                "status": {
                                    "type": "string",
                                    "enum": ["pending", "in_progress", "completed"],
                                },
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
    async def call(cls, arguments: str) -> model.ToolResultItem:
        try:
            args = TodoWriteArguments.model_validate_json(arguments)
        except ValueError as e:
            return model.ToolResultItem(
                status="error",
                output=f"Invalid arguments: {e}",
            )

        # Get current todo context to store todos
        todo_context = get_current_todo_context()
        if todo_context is None:
            return model.ToolResultItem(
                status="error",
                output="No active session found",
            )

        # Get current todos before updating (for comparison)
        old_todos = todo_context.get_todos()

        # Find newly completed todos
        new_completed = get_new_completed_todos(old_todos, args.todos)

        # Store todos via todo context
        todo_context.set_todos(args.todos)

        ui_extra = model.TodoUIExtra(todos=args.todos, new_completed=new_completed)

        response = f"""Todos have been modified successfully. Ensure that you continue to use the todo list to track your progress. Please proceed with the current tasks if applicable

<system-reminder>
Your todo list has changed. DO NOT mention this explicitly to the user. Here are the latest contents of your todo list:

{model.todo_list_str(args.todos)}. Continue on with the tasks at hand if applicable.
</system-reminder>"""

        return model.ToolResultItem(
            status="success",
            output=response,
            ui_extra=model.TodoListUIExtra(todo_list=ui_extra),
            side_effects=[model.ToolSideEffect.TODO_CHANGE],
        )
