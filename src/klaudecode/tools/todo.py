import json
from typing import Annotated, List, Literal

from pydantic import BaseModel, Field, RootModel
from rich.console import Group
from rich.text import Text

from ..message import ToolCall, ToolMessage, register_tool_call_renderer, register_tool_result_renderer
from ..prompt.tools import TODO_READ_RESULT, TODO_READ_TOOL_DESC, TODO_WRITE_RESULT, TODO_WRITE_TOOL_DESC
from ..tool import Tool, ToolInstance
from ..tui import ColorStyle, render_suffix

"""
Session-level To-Do
"""


class Todo(BaseModel):
    id: str
    content: str
    status: Literal['pending', 'completed', 'in_progress'] = 'pending'
    priority: Literal['low', 'medium', 'high'] = 'medium'


class TodoList(RootModel[List[Todo]]):
    root: List[Todo] = Field(default_factory=list)

    @property
    def todos(self):
        return self.root

    def __iter__(self):
        return iter(self.root)

    def __len__(self):
        return len(self.root)


class TodoWriteTool(Tool):
    name = 'TodoWrite'
    description = TODO_WRITE_TOOL_DESC
    parallelable: bool = True

    class Input(BaseModel):
        todo_list: Annotated[TodoList, Field(description='The updated todo list')]

    @classmethod
    def invoke(cls, tool_call: ToolCall, instance: 'ToolInstance'):
        args: 'TodoWriteTool.Input' = cls.parse_input_args(tool_call)

        instance.tool_result().set_content(TODO_WRITE_RESULT)

        old_todo_list = instance.parent_agent.session.todo_list
        old_todo_dict = {}
        if old_todo_list is not None:
            old_todo_dict = {todo.id: todo for todo in old_todo_list.root}

        instance.parent_agent.session.todo_list = args.todo_list
        new_completed_todos = []
        for todo in args.todo_list.root:
            if old_todo_list is not None and todo.id in old_todo_dict:
                old_todo = old_todo_dict[todo.id]
                if old_todo.status != 'completed' and todo.status == 'completed':
                    new_completed_todos.append(todo.id)

        instance.tool_result().set_extra_data('new_completed_todos', new_completed_todos)


class TodoReadTool(Tool):
    name = 'TodoRead'
    description = TODO_READ_TOOL_DESC

    class Input(BaseModel):
        pass

    @classmethod
    def invoke(cls, tool_call: ToolCall, instance: 'ToolInstance'):
        todo_list = instance.parent_agent.session.todo_list
        json_todo_list = json.dumps(todo_list.model_dump(), ensure_ascii=False)

        for todo in todo_list.root:
            instance.tool_result().append_extra_data('todo_list', todo.model_dump())

        instance.tool_result().set_content(TODO_READ_RESULT.format(todo_list_json=json_todo_list))


def render_todo_dict(todo: dict, new_completed: bool = False):
    content = todo['content']
    status = todo.get('status', 'pending')
    if status == 'completed' and new_completed:
        return Text.from_markup(f'☒ [s]{content}[/s]', style=ColorStyle.TODO_COMPLETED.value)
    elif status == 'completed':
        return Text.from_markup(f'☒ [s]{content}[/s]', style=ColorStyle.MUTED.value)
    elif status == 'in_progress':
        return Text.from_markup(f'☐ [bold]{content}[/bold]', style=ColorStyle.TODO_IN_PROGRESS.value)
    else:
        return f'☐ {content}'


def render_todo_read_result(tool_msg: ToolMessage):
    yield render_suffix(Group(*(render_todo_dict(todo) for todo in tool_msg.get_extra_data('todo_list'))))


def render_todo_write_result(tool_msg: ToolMessage):
    todo_list = tool_msg.tool_call.tool_args_dict.get('todo_list', {})
    new_completed_todos = tool_msg.get_extra_data('new_completed_todos', [])
    yield render_suffix(Group(*(render_todo_dict(todo, todo.get('id') in new_completed_todos) for todo in todo_list)))


def render_todo_write_name(tool_call: ToolCall):
    yield Text('Update Todos', 'bold')


def render_todo_read_name(tool_call: ToolCall):
    yield Text('Read Todos', 'bold')


register_tool_result_renderer('TodoRead', render_todo_read_result)
register_tool_result_renderer('TodoWrite', render_todo_write_result)
register_tool_call_renderer('TodoRead', render_todo_read_name)
register_tool_call_renderer('TodoWrite', render_todo_write_name)
