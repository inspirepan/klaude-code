import asyncio
import json
import signal
import threading
from abc import ABC
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from pydantic import BaseModel
from rich.console import Group
from rich.live import Live
from rich.text import Text

from .message import AIMessage, ToolCall, ToolMessage, count_tokens
from .tui import ColorStyle, console, render_status

if TYPE_CHECKING:
    from .agent import Agent


class Tool(ABC):
    """
    Tool is the base class for all tools.
    """

    name: str = ''
    desc: str = ''
    parallelable: bool = True
    timeout = 300

    @classmethod
    def get_name(cls) -> str:
        return cls.name

    @classmethod
    def get_desc(cls) -> str:
        return cls.desc

    @classmethod
    def is_parallelable(cls) -> bool:
        return cls.parallelable

    @classmethod
    def get_timeout(cls) -> float:
        return cls.timeout

    @classmethod
    def skip_in_tool_handler(cls) -> bool:
        return False

    @classmethod
    def get_parameters(cls) -> Dict[str, Any]:
        if hasattr(cls, 'parameters'):
            return cls.parameters

        if hasattr(cls, 'Input') and issubclass(cls.Input, BaseModel):
            schema = cls.Input.model_json_schema()
            return cls._resolve_schema_refs(schema)

        return {'type': 'object', 'properties': {}, 'required': []}

    @classmethod
    def tokens(cls) -> int:
        """Calculate total tokens for tool description and parameters"""
        desc_tokens = count_tokens(cls.get_desc())

        # Convert parameters to JSON string and count tokens
        params = cls.get_parameters()
        params_text = json.dumps(params, ensure_ascii=False)
        params_tokens = count_tokens(params_text)

        return desc_tokens + params_tokens

    @classmethod
    def _resolve_schema_refs(cls, schema: Dict[str, Any]) -> Dict[str, Any]:
        def resolve_refs(obj, defs_map):
            if isinstance(obj, dict):
                if '$ref' in obj:
                    ref_path = obj['$ref']
                    if ref_path.startswith('#/$defs/'):
                        def_name = ref_path.split('/')[-1]
                        if def_name in defs_map:
                            resolved = defs_map[def_name].copy()
                            return resolve_refs(resolved, defs_map)
                    return obj
                else:
                    return {k: resolve_refs(v, defs_map) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [resolve_refs(item, defs_map) for item in obj]
            else:
                return obj

        defs = schema.get('$defs', {})

        result = {
            'type': 'object',
            'properties': resolve_refs(schema.get('properties', {}), defs),
            'required': schema.get('required', []),
        }

        return result

    @classmethod
    def openai_schema(cls) -> Dict[str, Any]:
        return {
            'type': 'function',
            'function': {
                'name': cls.get_name(),
                'description': cls.get_desc(),
                'parameters': cls.get_parameters(),
            },
        }

    @classmethod
    def anthropic_schema(cls) -> Dict[str, Any]:
        return {
            'name': cls.get_name(),
            'description': cls.get_desc(),
            'input_schema': cls.get_parameters(),
        }

    def __str__(self) -> str:
        return self.json_openai_schema()

    def __repr__(self) -> str:
        return self.json_openai_schema()

    @classmethod
    def json_openai_schema(cls):
        return json.dumps(cls.openai_schema())

    @classmethod
    def create_instance(cls, tool_call: ToolCall, parent_agent: 'Agent') -> 'ToolInstance':
        return ToolInstance(tool=cls, tool_call=tool_call, parent_agent=parent_agent)

    @classmethod
    def parse_input_args(cls, tool_call: ToolCall) -> Optional[BaseModel]:
        if hasattr(cls, 'Input') and issubclass(cls.Input, BaseModel):
            args_dict = json.loads(tool_call.tool_args)
            input_inst = cls.Input(**args_dict)
            return input_inst
        return None

    @classmethod
    def invoke(cls, tool_call: ToolCall, instance: 'ToolInstance'):
        raise NotImplementedError

    @classmethod
    async def invoke_async(cls, tool_call: ToolCall, instance: 'ToolInstance'):
        loop = asyncio.get_event_loop()
        with ThreadPoolExecutor() as executor:

            def run_with_interrupt_check():
                # Provide interrupt check capability to sync tools
                return cls.invoke(tool_call, instance)

            future = loop.run_in_executor(executor, run_with_interrupt_check)
            try:
                await asyncio.wait_for(future, timeout=cls.get_timeout())
            except asyncio.CancelledError:
                instance._interrupt_flag.set()  # Signal the thread
                future.cancel()
                raise
            except asyncio.TimeoutError:
                instance._interrupt_flag.set()  # Signal the thread
                future.cancel()
                instance.tool_msg.tool_call.status = 'canceled'
                instance.tool_msg.content = f"Tool '{cls.get_name()}' timed out after {cls.get_timeout()}s"


class ToolInstance:
    """
    ToolInstance is the instance of a runtime tool call.
    """

    def __init__(self, tool: type[Tool], tool_call: ToolCall, parent_agent: 'Agent'):
        self.tool = tool
        self.tool_call = tool_call
        self.tool_msg: ToolMessage = ToolMessage(tool_call_id=tool_call.id, tool_call_cache=tool_call)
        self.parent_agent: 'Agent' = parent_agent

        self._task: Optional[asyncio.Task] = None
        self._is_running = False
        self._is_completed = False
        self._interrupt_flag = threading.Event()  # Thread-safe interrupt flag
        self._cancel_requested = False

    def tool_result(self) -> ToolMessage:
        return self.tool_msg

    async def start_async(self) -> asyncio.Task:
        if not self._task:
            self._is_running = True
            self._task = asyncio.create_task(self._run_async())
        return self._task

    async def _run_async(self):
        try:
            await self.tool.invoke_async(self.tool_call, self)
            self._is_completed = True
            if self.tool_msg.tool_call.status == 'processing':
                self.tool_msg.tool_call.status = 'success'
        except asyncio.CancelledError:
            self._is_completed = True
            raise
        except Exception as e:
            import traceback

            self.tool_msg.set_error_msg(str(e) + '\n' + traceback.format_exc())
            self._is_completed = True
        finally:
            self._is_running = False

    def is_running(self):
        return self._is_running and not self._is_completed

    def is_completed(self):
        return self._is_completed

    async def wait(self):
        if self._task:
            await self._task

    def cancel(self):
        self._cancel_requested = True
        self._interrupt_flag.set()  # Signal interruption to sync code
        if self._task and not self._task.done():
            self._task.cancel()
            self._is_completed = True
            self.tool_msg.tool_call.status = 'canceled'

    def is_cancelled(self) -> bool:
        """Check if cancellation was requested"""
        return self._cancel_requested or self._interrupt_flag.is_set()

    def check_interrupt(self) -> bool:
        """Check if tool should be interrupted (for use in sync code)"""
        return self._interrupt_flag.is_set()


class ToolHandler:
    """
    ToolHandler accepts a list of tool calls.
    """

    def __init__(self, agent, tools: List[Tool], show_live: bool = True):
        self.agent: 'Agent' = agent
        self.tool_dict = {tool.name: tool for tool in tools} if tools else {}
        self.show_live = show_live
        self._global_interrupt = threading.Event()  # Global interrupt flag

    async def handle(self, ai_message: AIMessage):
        if not ai_message.tool_calls or not len(ai_message.tool_calls):
            return

        parallelable_tool_calls = []
        non_parallelable_tool_calls = []
        for tool_call in ai_message.tool_calls.values():
            if tool_call.tool_name not in self.tool_dict:
                pass
            if self.tool_dict[tool_call.tool_name].skip_in_tool_handler():
                continue
            if self.tool_dict[tool_call.tool_name].is_parallelable():
                parallelable_tool_calls.append(tool_call)
            else:
                non_parallelable_tool_calls.append(tool_call)

        # Handle parallelable tools first
        await self.handle_tool_calls(parallelable_tool_calls)

        # Handle non-parallelable tools one by one
        for tc in non_parallelable_tool_calls:
            await self.handle_tool_calls([tc])

    async def handle_tool_calls(self, tool_calls: List[ToolCall]):
        """Unified method to handle both single and multiple tool calls."""
        if not tool_calls:
            return

        tool_instances = [self.tool_dict[tc.tool_name].create_instance(tc, self.agent) for tc in tool_calls]
        tasks = [await ti.start_async() for ti in tool_instances]

        interrupted = False
        signal_handler_added = False

        def signal_handler(*args):
            nonlocal interrupted
            interrupted = True
            self._global_interrupt.set()  # Set global interrupt flag
            for ti in tool_instances:
                ti.cancel()

        # Backup interrupt checking for scenarios where signal handler fails
        async def interrupt_monitor():
            while not interrupted and any(ti.is_running() for ti in tool_instances):
                try:
                    # Check if any external interrupt mechanism triggered
                    if hasattr(self.agent, '_should_interrupt') and self.agent._should_interrupt():
                        signal_handler()
                        break
                    await asyncio.sleep(0.05)  # Check every 50ms
                except asyncio.CancelledError:
                    break

        try:
            monitor_task = None
            try:
                loop = asyncio.get_event_loop()
                loop.add_signal_handler(signal.SIGINT, signal_handler)
                signal_handler_added = True
            except (ValueError, NotImplementedError, OSError, RuntimeError):
                # Signal handling not available in this context (e.g., subthread)
                # Start backup interrupt monitoring
                monitor_task = asyncio.create_task(interrupt_monitor())

            if self.show_live:
                try:
                    # Generate status text based on number of tools
                    if len(tool_calls) == 1:
                        status_text = Text.assemble('Executing ', (ToolCall.get_display_tool_name(tool_calls[0].tool_name), ColorStyle.HIGHLIGHT.bold()), '...')
                    else:
                        tool_counts = {}
                        for tc in tool_calls:
                            tool_counts[tc.tool_name] = tool_counts.get(tc.tool_name, 0) + 1
                        tool_names = [
                            Text.assemble((ToolCall.get_display_tool_name(name), ColorStyle.HIGHLIGHT.bold()), '*' + str(count) if count > 1 else '', ' ')
                            for name, count in tool_counts.items()
                        ]
                        status_text = Text.assemble('Executing ', *tool_names, '...')

                    status = render_status(status_text)
                except Exception as e:
                    print(str(e))
                with Live(refresh_per_second=10, console=console.console) as live:
                    live_group = []
                    for ti in tool_instances:
                        live_group.append('')
                        live_group.append(ti.tool_result())
                    while any(ti.is_running() for ti in tool_instances) and not interrupted:
                        live.update(Group(*live_group, status))
                        await asyncio.sleep(0.1)
                    live.update(Group(*live_group))

            await asyncio.gather(*tasks, return_exceptions=True)

        finally:
            if signal_handler_added:
                try:
                    loop.remove_signal_handler(signal.SIGINT)
                except (ValueError, NotImplementedError, OSError):
                    pass
            if monitor_task:
                monitor_task.cancel()
                try:
                    await monitor_task
                except asyncio.CancelledError:
                    pass
            self.agent.session.append_message(*(ti.tool_result() for ti in tool_instances))
            if interrupted:
                raise asyncio.CancelledError


UPDATE_STATUS_TEXTS = ['Updating', 'Modifying', 'Changing', 'Refactoring', 'Transforming', 'Rewriting', 'Refining', 'Polishing', 'Tweaking', 'Adjusting', 'Fixing']
TODO_STATUS_TEXTS = ['Planning', 'Organizing', 'Structuring', 'Brainstorming', 'Strategizing', 'Outlining', 'Tracking']

TOOL_CALL_STATUS_TEXT_DICT = {
    'MultiEdit': UPDATE_STATUS_TEXTS,
    'Edit': UPDATE_STATUS_TEXTS,
    'Read': ['Exploring', 'Reading', 'Scanning', 'Analyzing', 'Inspecting', 'Examining', 'Studying'],
    'Write': ['Writing', 'Creating', 'Crafting', 'Composing', 'Generating'],
    'TodoWrite': TODO_STATUS_TEXTS,
    'TodoRead': TODO_STATUS_TEXTS,
    'LS': ['Exploring', 'Scanning', 'Browsing', 'Investigating', 'Surveying', 'Discovering', 'Wandering'],
    'Grep': ['Searching', 'Looking', 'Finding', 'Hunting', 'Tracking', 'Filtering', 'Digging'],
    'Glob': ['Searching', 'Looking', 'Finding', 'Matching', 'Collecting', 'Gathering', 'Harvesting'],
    'Bash': ['Executing', 'Running', 'Processing', 'Computing', 'Launching', 'Invoking', 'Commanding'],
    'ExitPlanMode': ['Planning'],
    'CommandPatternResult': ['Patterning'],
}


def get_tool_call_status_text(tool_name: str, seed: Optional[int] = None) -> str:
    """
    Write -> Writing
    """
    if seed is not None:
        import random

        random.seed(seed)

    if tool_name in TOOL_CALL_STATUS_TEXT_DICT:
        return random.choice(TOOL_CALL_STATUS_TEXT_DICT[tool_name]) + '...'
    if tool_name.startswith('mcp__'):
        return 'Executing...'
    if tool_name.endswith('e'):
        return f'{tool_name[:-1]}ing...'
    return f'{tool_name}ing...'
