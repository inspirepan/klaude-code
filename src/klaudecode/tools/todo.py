import json
from typing import Annotated, List, Literal

from pydantic import BaseModel, Field, RootModel
from rich.console import Group
from rich.padding import Padding
from rich.text import Text

from ..message import ToolCall, ToolMessage, register_tool_call_renderer, register_tool_result_renderer
from ..prompt.reminder import TODO_REMINDER
from ..prompt.tools import TODO_READ_RESULT, TODO_READ_TOOL_DESC, TODO_WRITE_RESULT, TODO_WRITE_TOOL_DESC
from ..tool import Tool, ToolInstance
from ..tui import ColorStyle, render_suffix

"""
- Session-persistent task management with status tracking
- Priority levels and progress indicators with rich visual feedback
- JSON-based storage format for seamless serialization
- Real-time completion notifications and state change detection
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
    desc = TODO_WRITE_TOOL_DESC
    parallelable: bool = True

    class Input(BaseModel):
        todos: Annotated[TodoList, Field(description='The updated todo list')]

    @classmethod
    def invoke(cls, tool_call: ToolCall, instance: 'ToolInstance'):
        args: 'TodoWriteTool.Input' = cls.parse_input_args(tool_call)
        json_todo_list = json.dumps(args.todos.model_dump(), ensure_ascii=False)
        reminder = TODO_REMINDER.format(todo_list_json=json_todo_list)
        instance.tool_result().set_content(TODO_WRITE_RESULT + '\n' + reminder)

        old_todo_list = instance.agent_state.session.todo_list
        old_todo_dict = {}
        if old_todo_list is not None:
            old_todo_dict = {todo.id: todo for todo in old_todo_list.root}

        instance.agent_state.session.todo_list = args.todos
        new_completed_todos = []
        for todo in args.todos.root:
            if old_todo_list is not None and todo.id in old_todo_dict:
                old_todo = old_todo_dict[todo.id]
                if old_todo.status != 'completed' and todo.status == 'completed':
                    new_completed_todos.append(todo.id)

        instance.tool_result().set_extra_data('new_completed_todos', new_completed_todos)


class TodoReadTool(Tool):
    name = 'TodoRead'
    desc = TODO_READ_TOOL_DESC

    class Input(BaseModel):
        pass

    @classmethod
    def invoke(cls, tool_call: ToolCall, instance: 'ToolInstance'):
        todo_list = instance.agent_state.session.todo_list
        json_todo_list = json.dumps(todo_list.model_dump(), ensure_ascii=False)

        for todo in todo_list.root:
            instance.tool_result().append_extra_data('todo_list', todo.model_dump())

        instance.tool_result().set_content(TODO_READ_RESULT.format(todo_list_json=json_todo_list))


def render_todo_dict(todo: dict, new_completed: bool = False):
    content = todo['content']
    status = todo.get('status', 'pending')
    if status == 'completed' and new_completed:
        return Text.from_markup(f'☒ [s]{content}[/s]', style=ColorStyle.TODO_COMPLETED)
    elif status == 'completed':
        return Text.from_markup(f'☒ [s]{content}[/s]')
    elif status == 'in_progress':
        return Text.from_markup(f'☐ [bold]{content}[/bold]', style=ColorStyle.TODO_IN_PROGRESS)
    else:
        return f'☐ {content}'


@register_tool_result_renderer(TodoReadTool.name)
def render_todo_read_result(tool_msg: ToolMessage):
    if tool_msg.get_extra_data('todo_list') is None:
        yield render_suffix('(No Content)')
        return
    yield render_suffix(Group(*(render_todo_dict(todo) for todo in tool_msg.get_extra_data('todo_list'))))


@register_tool_result_renderer(TodoWriteTool.name)
def render_todo_write_result(tool_msg: ToolMessage):
    todo_list = tool_msg.tool_call.tool_args_dict.get('todos', {})
    new_completed_todos = tool_msg.get_extra_data('new_completed_todos', [])
    yield render_suffix(Group(*(render_todo_dict(todo, todo.get('id') in new_completed_todos) for todo in todo_list)))


@register_tool_call_renderer(TodoWriteTool.name)
def render_todo_write_name(tool_call: ToolCall, is_suffix: bool = False):
    if not is_suffix:
        yield Text('Update Todos', ColorStyle.TOOL_NAME.bold)
        return
    # For todo in task
    in_progress_todos = []
    pending_todos = []
    all_completed = True
    all_pending = True
    for todo in tool_call.tool_args_dict.get('todos', {}):
        if todo.get('status') == 'in_progress':
            in_progress_todos.append(todo.get('content'))
        if todo.get('status') != 'completed':
            all_completed = False
        if todo.get('status') == 'pending':
            pending_todos.append(todo.get('content'))
        if todo.get('status') != 'pending':
            all_pending = False
    if all_completed:
        yield Text.assemble(('Update Todos', ColorStyle.MAIN.bold), '(', ('All Completed', ColorStyle.TODO_COMPLETED.bold), ')')
    elif all_pending:
        yield Text.assemble(('Update Todos', ColorStyle.MAIN.bold))
        yield Padding.indent(Group(*(Text(f'☐ {todo}') for todo in pending_todos)), 2)
    elif in_progress_todos:
        yield Text.assemble(('Update Todos', ColorStyle.MAIN.bold), '(', (f'{", ".join(in_progress_todos)}', ColorStyle.TODO_IN_PROGRESS), ')')
    else:
        yield Text('Update Todos', ColorStyle.TOOL_NAME.bold)


@register_tool_call_renderer(TodoReadTool.name)
def render_todo_read_name(tool_call: ToolCall, is_suffix: bool = False):
    yield Text('Read Todos', ColorStyle.TOOL_NAME.bold if not is_suffix else ColorStyle.MAIN.bold)
