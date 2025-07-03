import asyncio
import gc
import warnings
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

from pydantic import BaseModel, Field
from rich.panel import Panel
from rich.text import Text

from ..message import AIMessage, BasicMessage, SystemMessage, ToolCall, ToolMessage, UserMessage, register_tool_call_renderer, register_tool_result_renderer
from ..prompt.system import get_subagent_system_prompt
from ..prompt.tools import TASK_TOOL_DESC
from ..session import Session
from ..tool import ToolInstance
from ..tui import ColorStyle, render_markdown, render_suffix
from ..utils.exception import format_exception
from . import BASIC_TOOLS

DEFAULT_MAX_STEPS = 80

if TYPE_CHECKING:
    from ..agent import Agent


class TaskToolMixin:
    """Mixin that provides Task tool functionality for Agent"""

    name = 'Task'
    desc = TASK_TOOL_DESC
    parallelable: bool = True

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
                if msg.tool_calls:
                    for tool_call in msg.tool_calls.values():
                        instance.tool_result().append_extra_data('tool_calls', tool_call.model_dump())

        session = Session(
            work_dir=Path.cwd(),
            messages=[SystemMessage(content=get_subagent_system_prompt(work_dir=instance.parent_agent.session.work_dir, model_name=instance.parent_agent.config.model_name.value))],
            append_message_hook=subagent_append_message_hook,
            source='subagent',
        )
        agent: 'Agent' = cls(session, availiable_tools=cls.get_subagent_tools(), print_switch=False, config=instance.parent_agent.config)
        # Initialize LLM manager for subagent
        agent._initialize_llm()
        agent.session.append_message(UserMessage(content=args.prompt))

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
                    agent.run(max_steps=DEFAULT_MAX_STEPS, check_interrupt=lambda: instance.tool_result().tool_call.status == 'canceled', tools=cls.get_subagent_tools())
                )
                # Update parent agent usage with subagent usage
                instance.parent_agent.usage.update_with_usage(agent.usage)
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


def render_agent_args(tool_call: ToolCall, is_suffix: bool = False):
    yield Text.assemble(
        (tool_call.tool_name, ColorStyle.HIGHLIGHT.bold),
        '(',
        (tool_call.tool_args_dict.get('description', ''), ColorStyle.HIGHLIGHT.bold),
        ')',
        ' → ',
        tool_call.tool_args_dict.get('prompt', ''),
    )


def render_agent_result(tool_msg: ToolMessage):
    tool_calls = tool_msg.get_extra_data('tool_calls')
    if tool_calls:
        for subagent_tool_call_dcit in tool_calls:
            tool_call = ToolCall(**subagent_tool_call_dcit)
            yield from (render_suffix(item) for item in tool_call.get_suffix_renderable())
        count = len(tool_calls)
        yield render_suffix(f'({count} tool use{"" if count == 1 else "s"})')
    if tool_msg.content:
        yield render_suffix(Panel.fit(render_markdown(tool_msg.content), border_style=ColorStyle.AGENT_BORDER))


# Register renderers
register_tool_call_renderer('Task', render_agent_args)
register_tool_result_renderer('Task', render_agent_result)
