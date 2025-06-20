import json
from typing import Annotated, List, Literal, Optional, Tuple

from pydantic import BaseModel, Field

from ..prompt.tools import TODO_READ_AI_RESULT_TEMPLATE, TODO_READ_TOOL_DESC, TODO_WRITE_AI_RESULT, TODO_WRITE_TOOL_DESC
from ..tool import Tool, ToolInstance
from ..message import ToolCall

"""
Session-level To-Do
"""


class Todo(BaseModel):
    id: Annotated[
        str,
        "A semantic slug-style id based on todo content (e.g. 'implement-user-auth', 'fix-login-bug', 'add-dark-mode'). Use lowercase, hyphens for spaces, and keep it descriptive but concise.",
    ]
    content: Annotated[str, 'The content of the todo']
    status: Annotated[Literal['pending', 'completed', 'in_progress'], 'The status of the todo'] = 'pending'
    priority: Annotated[Literal['low', 'medium', 'high'], 'The priority of the todo'] = 'medium'

    def __rich_console__(self, console, options):
        if self.status == 'completed':
            yield f'[green] ☒ [s]{self.content}[/s][/green]'
        elif self.status == 'in_progress':
            yield f'[blue] ☐ [bold]{self.content}[/bold][/blue]'
        else:
            yield f'[blue] ☐ [bold]{self.content}[/bold][/blue]'


class TodoList(BaseModel):
    todos: Annotated[List[Todo], Field(description='The list of todos')] = Field(default_factory=list)

    def __rich_console__(self, console, options):
        for todo in self.todos:
            yield todo


class TodoWriteTool(Tool):
    name = "TodoWrite"
    description = TODO_WRITE_TOOL_DESC

    class Input(BaseModel):
        todo_list: TodoList

    @classmethod
    def invoke(cls, tool_call: ToolCall, instance: 'ToolInstance'):
        args: 'TodoWriteTool.Input' = cls.parse_input_args(tool_call)

        instance.tool_result().tool_call.hide_args = True
        instance.tool_result().nice_content = args.todo_list
        instance.tool_result().set_content(TODO_WRITE_AI_RESULT)
        instance.parent_agent.session.todo_list = args.todo_list


class TodoReadTool(Tool):
    name = "TodoRead"
    description = TODO_READ_TOOL_DESC

    class Input(BaseModel):
        pass

    @classmethod
    def invoke(cls, tool_call: ToolCall, instance: 'ToolInstance'):
        todo_list = instance.parent_agent.session.todo_list
        json_todo_list = json.dumps(todo_list.model_dump())
        instance.tool_result().tool_call.hide_args = True
        instance.tool_result().nice_content = todo_list
        instance.tool_result().set_content(TODO_READ_AI_RESULT_TEMPLATE.format(todo_list_json=json_todo_list))
