import asyncio
import gc
import warnings
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

from pydantic import BaseModel, Field
from rich import box
from rich.columns import Columns
from rich.console import Group
from rich.panel import Panel
from rich.rule import Rule
from rich.text import Text

from ..agent_state import AgentState
from ..message import AIMessage, BasicMessage, SystemMessage, ToolCall, ToolMessage, UserMessage, register_tool_call_renderer, register_tool_result_renderer
from ..prompt.system import get_subagent_system_prompt
from ..prompt.tools import TASK_TOOL_DESC
from ..session import Session
from ..tool import ToolInstance
from ..tui import ColorStyle, render_markdown, render_suffix
from ..utils.exception import format_exception
from ..utils.str_utils import truncate_char
from . import BASIC_TOOLS

DEFAULT_MAX_STEPS = 80

if TYPE_CHECKING:
    from ..agent_executor import AgentExecutor


class TaskToolMixin:
    """Mixin that provides Task tool functionality for Agent"""

    name = 'Task'
    desc = TASK_TOOL_DESC
    parallelable: bool = True
    timeout = 900

    class Input(BaseModel):
        description: Annotated[str, Field(description='A short (3-5 word) description of the task')]
        prompt: Annotated[str, Field(description='The task for the agent to perform')]

    @classmethod
    def get_subagent_tools(cls):
        return BASIC_TOOLS

    @classmethod
    def invoke(cls, tool_call: ToolCall, instance: 'ToolInstance'):
        args: 'TaskToolMixin.Input' = cls.parse_input_args(tool_call)

        def subagent_append_message_hook(*msgs: BasicMessage) -> None:
            if not msgs:
                return
            for msg in msgs:
                if not isinstance(msg, AIMessage):
                    continue
                task_msg_data = {'content': msg.content, 'tool_calls': [tool_call.model_dump() for tool_call in msg.tool_calls.values()] if msg.tool_calls else []}
                instance.tool_result().append_extra_data('task_msgs', task_msg_data)

        sub_agent_session = Session(
            work_dir=Path.cwd(),
            messages=[SystemMessage(content=get_subagent_system_prompt(work_dir=instance.agent_state.session.work_dir, model_name=instance.agent_state.config.model_name.value))],
            source='subagent',
        )
        sub_agent_session.set_append_message_hook(subagent_append_message_hook)
        sub_agent_state: 'AgentState' = AgentState(sub_agent_session, config=instance.agent_state.config, available_tools=cls.get_subagent_tools(), print_switch=False)
        sub_agent: 'AgentExecutor' = cls(sub_agent_state)
        # Initialize LLM manager for subagent
        sub_agent.agent_state.initialize_llm()
        sub_agent.agent_state.session.append_message(UserMessage(content=args.prompt))

        # Use asyncio.run with proper isolation and error suppression
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', ResourceWarning)
            warnings.simplefilter('ignore', RuntimeWarning)

            # Set custom exception handler to suppress cleanup errors
            def exception_handler(loop, context):
                # Ignore "Event loop is closed" and similar cleanup errors
                if 'Event loop is closed' in str(context.get('exception', '')):
                    return
                if 'aclose' in str(context.get('exception', '')):
                    return
                # Log other exceptions normally
                loop.default_exception_handler(context)

            try:
                loop = asyncio.new_event_loop()
                loop.set_exception_handler(exception_handler)
                asyncio.set_event_loop(loop)
                result = loop.run_until_complete(
                    sub_agent.run(max_steps=DEFAULT_MAX_STEPS, check_cancel=lambda: instance.tool_result().tool_call.status == 'canceled', tools=cls.get_subagent_tools())
                )
                # Update parent agent usage with subagent usage
                instance.agent_state.usage.update_with_usage(sub_agent.agent_state.usage)
            except Exception as e:
                result = f'SubAgent error: {format_exception(e)}'
            finally:
                try:
                    # Suppress any remaining tasks
                    pending = asyncio.all_tasks(loop)
                    for task in pending:
                        task.cancel()
                    if pending:
                        loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                except Exception:
                    pass
                finally:
                    asyncio.set_event_loop(None)
                    # Don't close loop explicitly to avoid cleanup issues
                    # Force garbage collection to trigger any delayed HTTP client cleanup
                    gc.collect()

        instance.tool_result().set_content((result or '').strip())


def render_task_args(tool_call: ToolCall, is_suffix: bool = False):
    yield Columns(
        [
            Text.assemble((tool_call.tool_name, ColorStyle.TOOL_NAME.bold), '(', (tool_call.tool_args_dict.get('description', ''), ColorStyle.TOOL_NAME.bold), ')', ' →'),
            Group(Text(tool_call.tool_args_dict.get('prompt', ''), style=ColorStyle.TOOL_NAME), Rule(style=ColorStyle.LINE, characters='╌')),
        ],
    )


def _render_tool_calls(tool_calls):
    """Render tool calls to renderable elements using generator"""
    for tool_call_dict in tool_calls:
        tool_call = ToolCall(**tool_call_dict)
        yield from tool_call.get_suffix_renderable()


def _render_processing_status(task_msgs: list):
    """Render task in processing status"""
    msgs_to_show = []
    for i in range(len(task_msgs) - 1, -1, -1):
        msg = task_msgs[i]
        msgs_to_show.append(msg)

        if (msg.get('content') and msg['content'].strip()) or len(msgs_to_show) >= 3:
            break

    msgs_to_show.reverse()

    def generate_elements():
        for msg in msgs_to_show:
            if msg.get('content') and msg['content'].strip():
                yield Text(truncate_char(msg['content']))

            tool_calls = msg.get('tool_calls', [])
            if tool_calls:
                yield from _render_tool_calls(tool_calls)

        shown_msgs_count = len(msgs_to_show)
        if shown_msgs_count < len(task_msgs):
            remaining_tool_calls = sum(len(task_msgs[i].get('tool_calls', [])) for i in range(len(task_msgs) - shown_msgs_count))
            if remaining_tool_calls > 0:
                yield Text(f'+ {remaining_tool_calls} more tool use{"" if remaining_tool_calls == 1 else "s"}', style=ColorStyle.TOOL_NAME)

    return render_suffix(Group(*generate_elements()))


def _render_completed_status(content: str, task_msgs: list):
    """Render task in completed status"""
    # Use generator to avoid creating intermediate list
    all_tool_calls = (tool_call for task_msg in task_msgs for tool_call in task_msg.get('tool_calls', []))

    # Check if there are any tool calls by trying to get the first one
    tool_call_gen = _render_tool_calls(all_tool_calls)
    for tool_call in tool_call_gen:
        yield render_suffix(tool_call)

    if content:
        yield render_suffix(Panel.fit(render_markdown(content, style=ColorStyle.AI_CONTENT), border_style=ColorStyle.LINE, width=80, box=box.ROUNDED))


def render_task_result(tool_msg: ToolMessage):
    task_msgs = tool_msg.get_extra_data('task_msgs')
    if task_msgs:
        if tool_msg.tool_call.status == 'processing':
            yield _render_processing_status(task_msgs)
        elif tool_msg.tool_call.status == 'canceled':
            return
        else:
            yield from _render_completed_status(tool_msg.content, task_msgs)
    else:
        yield render_suffix('Initializing...')


# Register renderers
register_tool_call_renderer('Task', render_task_args)
register_tool_result_renderer('Task', render_task_result)
