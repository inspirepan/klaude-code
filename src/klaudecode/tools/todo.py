import json
from typing import Annotated, List, Literal

from pydantic import BaseModel, Field
from rich.console import Group

from ..message import (ToolCall, ToolMessage, register_tool_call_renderer,
                       register_tool_result_renderer)
from ..prompt.tools import (TODO_READ_AI_RESULT_TEMPLATE, TODO_READ_TOOL_DESC,
                            TODO_WRITE_AI_RESULT, TODO_WRITE_TOOL_DESC)
from ..tool import Tool, ToolInstance
from ..tui import format_style, render_suffix

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


class TodoList(BaseModel):
    todos: Annotated[List[Todo], Field(description='The list of todos')] = Field(default_factory=list)

    def __rich_console__(self, console, options):
        for todo in self.todos:
            yield todo


class TodoWriteTool(Tool):
    name = 'TodoWrite'
    description = TODO_WRITE_TOOL_DESC

    class Input(BaseModel):
        todo_list: TodoList

    @classmethod
    def invoke(cls, tool_call: ToolCall, instance: 'ToolInstance'):
        args: 'TodoWriteTool.Input' = cls.parse_input_args(tool_call)

        instance.tool_result().set_content(TODO_WRITE_AI_RESULT)

        old_todo_list = instance.parent_agent.session.todo_list
        old_todo_dict = {}
        if old_todo_list is not None:
            old_todo_dict = {todo.id: todo for todo in old_todo_list.todos}

        instance.parent_agent.session.todo_list = args.todo_list
        for todo in args.todo_list.todos:
            todo_data = todo.model_dump()

            if old_todo_list is not None and todo.id in old_todo_dict:
                old_todo = old_todo_dict[todo.id]
                if old_todo.status != 'completed' and todo.status == 'completed':
                    todo_data['new_completed'] = True

            instance.tool_result().add_extra_data(todo_data)


class TodoReadTool(Tool):
    name = 'TodoRead'
    description = TODO_READ_TOOL_DESC

    class Input(BaseModel):
        pass

    @classmethod
    def invoke(cls, tool_call: ToolCall, instance: 'ToolInstance'):
        todo_list = instance.parent_agent.session.todo_list
        json_todo_list = json.dumps(todo_list.model_dump())

        for todo in todo_list.todos:
            instance.tool_result().add_extra_data(todo.model_dump())

        instance.tool_result().set_content(TODO_READ_AI_RESULT_TEMPLATE.format(todo_list_json=json_todo_list))


def render_todo_dict(todo: dict):
    content = todo['content']
    status = todo['status']
    if status == 'completed' and todo.get('new_completed', False):
        return f'[green] ☒ [s]{content}[/s][/green]'
    elif status == 'completed':
        return f' ☒ [s]{content}[/s]'
    elif status == 'in_progress':
        return f'[blue] ☐ [bold]{content}[/bold][/blue]'
    else:
        return f' ☐ {content}'


def render_todo_result(tool_msg: ToolMessage):
    yield render_suffix(Group(*[render_todo_dict(todo) for todo in tool_msg.extra_data]))


def render_todo_write_name(tool_call: ToolCall):
    yield format_style('Update Todos', 'bold')


def render_todo_read_name(tool_call: ToolCall):
    yield format_style('Read Todos', 'bold')


register_tool_result_renderer('TodoRead', render_todo_result)
register_tool_result_renderer('TodoWrite', render_todo_result)
register_tool_call_renderer('TodoRead', render_todo_read_name)
register_tool_call_renderer('TodoWrite', render_todo_write_name)
