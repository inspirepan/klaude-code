import asyncio
import gc
import warnings
from abc import abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING, List

from rich import box
from rich.columns import Columns
from rich.console import Group
from rich.panel import Panel
from rich.rule import Rule
from rich.text import Text

from ..message import AIMessage, BasicMessage, SystemMessage, ToolCall, ToolMessage, UserMessage, register_tool_call_renderer, register_tool_result_renderer
from ..session import Session
from ..tool import Tool
from ..tui import ColorStyle, render_markdown, render_suffix
from ..utils.exception import format_exception
from ..utils.str_utils import truncate_char

if TYPE_CHECKING:
    from ..tool import ToolInstance
    from .state import AgentState


DEFAULT_MAX_STEPS = 80


# Metaclass to automatically register renderers when a subclass is defined
class SubAgentMeta(type(Tool)):
    def __new__(cls, name, bases, dct):
        new_class = super().__new__(cls, name, bases, dct)
        # Only register renderers for concrete subclasses (not the base class)
        if name != 'SubAgentBase':
            # Check if this class inherits from SubAgentBase (by name, not issubclass to avoid circular issues)
            has_subagent_base = any(base.__name__ == 'SubAgentBase' for base in bases)
            if has_subagent_base and hasattr(new_class, 'name'):
                register_tool_call_renderer(new_class.name, new_class.render_tool_call_args)
                register_tool_result_renderer(new_class.name, new_class.render_tool_result)
        return new_class


class SubAgentBase(Tool, metaclass=SubAgentMeta):
    """Abstract base class for sub-agents"""

    parallelable: bool = True
    timeout: int = 900

    @classmethod
    @abstractmethod
    def get_system_prompt(cls, work_dir: Path, model_name: str) -> str:
        """Get the system prompt for this sub-agent"""
        pass

    @classmethod
    @abstractmethod
    def get_subagent_tools(cls) -> List[Tool]:
        """Get the tools available to this sub-agent"""
        pass

    @classmethod
    def invoke(cls, tool_call, instance: 'ToolInstance'):
        """Common sub-agent invocation logic"""
        args = cls.parse_input_args(tool_call)

        return SubAgentFramework.execute_subagent(
            prompt=args.prompt,
            system_prompt=cls.get_system_prompt(work_dir=instance.agent_state.session.work_dir, model_name=instance.agent_state.config.model_name.value),
            tools=cls.get_subagent_tools(),
            agent_state=instance.agent_state,
            tool_instance=instance,
        )

    @classmethod
    def render_tool_call_args(cls, tool_call: ToolCall, is_suffix: bool = False):
        """Default renderer for tool call arguments. Can be overridden by subclasses."""
        yield Columns(
            [
                Text.assemble((tool_call.tool_name, ColorStyle.TOOL_NAME.bold), '(', (tool_call.tool_args_dict.get('description', ''), ColorStyle.TOOL_NAME.bold), ')', ' →'),
                Group(Text(tool_call.tool_args_dict.get('prompt', ''), style=ColorStyle.TOOL_NAME), Rule(style=ColorStyle.LINE, characters='╌')),
            ],
        )

    @classmethod
    def render_tool_result(cls, tool_msg: ToolMessage):
        """Default renderer for tool results. Can be overridden by subclasses."""
        task_msgs = tool_msg.get_extra_data('task_msgs')
        if task_msgs:
            if tool_msg.tool_call.status == 'processing':
                yield cls._render_processing_status(task_msgs)
            elif tool_msg.tool_call.status == 'canceled':
                return
            else:
                yield from cls._render_completed_status(tool_msg.content, task_msgs)
        else:
            yield render_suffix('Initializing...')

    @classmethod
    def _render_tool_calls(cls, tool_calls):
        """Render tool calls to renderable elements using generator"""
        for tool_call_dict in tool_calls:
            tool_call = ToolCall(**tool_call_dict)
            yield from tool_call.get_suffix_renderable()

    @classmethod
    def _render_processing_status(cls, task_msgs: list):
        """Render task in processing status"""
        msgs_to_show = []
        for msg in reversed(task_msgs):
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
                    yield from cls._render_tool_calls(tool_calls)

            shown_msgs_count = len(msgs_to_show)
            if shown_msgs_count < len(task_msgs):
                remaining_tool_calls = sum(len(task_msgs[i].get('tool_calls', [])) for i in range(len(task_msgs) - shown_msgs_count))
                if remaining_tool_calls > 0:
                    yield Text(f'+ {remaining_tool_calls} more tool use{"" if remaining_tool_calls == 1 else "s"}', style=ColorStyle.TOOL_NAME)

        return render_suffix(Group(*generate_elements()))

    @classmethod
    def _render_completed_status(cls, content: str, task_msgs: list):
        """Render task in completed status"""
        # Use generator to avoid creating intermediate list
        all_tool_calls = (tool_call for task_msg in task_msgs for tool_call in task_msg.get('tool_calls', []))

        # Check if there are any tool calls by trying to get the first one
        tool_call_gen = cls._render_tool_calls(all_tool_calls)
        for tool_call in tool_call_gen:
            yield render_suffix(tool_call)

        if content:
            yield render_suffix(Panel.fit(render_markdown(content, style=ColorStyle.AI_CONTENT), border_style=ColorStyle.LINE, width=100, box=box.ROUNDED))


class SubAgentFramework:
    """Framework for executing sub-agents with common logic"""

    @classmethod
    def execute_subagent(cls, prompt: str, system_prompt: str, tools: List[Tool], agent_state: 'AgentState', tool_instance: 'ToolInstance') -> str:
        """Execute a sub-agent with the given configuration"""

        def subagent_append_message_hook(*msgs: BasicMessage) -> None:
            if not msgs:
                return
            for msg in msgs:
                if not isinstance(msg, AIMessage):
                    continue
                task_msg_data = {'content': msg.content, 'tool_calls': [tool_call.model_dump() for tool_call in msg.tool_calls.values()] if msg.tool_calls else []}
                tool_instance.tool_result().append_extra_data('task_msgs', task_msg_data)

        from .executor import AgentExecutor
        from .state import AgentState

        sub_agent_session = Session(
            work_dir=Path.cwd(),
            messages=[SystemMessage(content=system_prompt)],
            source='subagent',
        )
        sub_agent_session.set_append_message_hook(subagent_append_message_hook)
        sub_agent_state: 'AgentState' = AgentState(sub_agent_session, config=agent_state.config, available_tools=tools, print_switch=False)
        sub_agent: 'AgentExecutor' = AgentExecutor(sub_agent_state)

        # Initialize LLM manager for subagent
        sub_agent.agent_state.initialize_llm()
        sub_agent.agent_state.session.append_message(UserMessage(content=prompt))

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
                    sub_agent.run(max_steps=DEFAULT_MAX_STEPS, check_cancel=lambda: tool_instance.tool_result().tool_call.status == 'canceled', tools=tools)
                )
                # Update parent agent usage with subagent usage
                agent_state.usage.update_with_usage(sub_agent.agent_state.usage)
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

        tool_instance.tool_result().set_content((result or '').strip())
        return result
