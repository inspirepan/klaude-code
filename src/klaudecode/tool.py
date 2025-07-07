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
from .tui import ColorStyle, console, render_dot_status
from .utils.exception import format_exception

if TYPE_CHECKING:
    from .agent_state import AgentState


class ToolSchema:
    """Handles tool schema generation and parameter parsing."""

    @staticmethod
    def get_parameters(tool_class: type) -> Dict[str, Any]:
        """Get tool parameters schema."""
        if hasattr(tool_class, 'parameters'):
            return tool_class.parameters

        if ToolSchema._has_input_model(tool_class):
            return ToolSchema._get_parameters_from_input_model(tool_class)

        return ToolSchema._get_default_parameters()

    @staticmethod
    def _has_input_model(tool_class: type) -> bool:
        """Check if the tool has an Input model."""
        return hasattr(tool_class, 'Input') and issubclass(tool_class.Input, BaseModel)

    @staticmethod
    def _get_parameters_from_input_model(tool_class: type) -> Dict[str, Any]:
        """Extract parameters from the Input model."""
        schema = tool_class.Input.model_json_schema()
        return ToolSchema._resolve_schema_refs(schema)

    @staticmethod
    def _get_default_parameters() -> Dict[str, Any]:
        """Return default empty parameters schema."""
        return {'type': 'object', 'properties': {}, 'required': []}

    @staticmethod
    def _resolve_schema_refs(schema: Dict[str, Any]) -> Dict[str, Any]:
        """Resolve JSON schema references ($ref) in the schema."""
        defs = schema.get('$defs', {})

        result = {
            'type': 'object',
            'properties': ToolSchema._resolve_refs_in_object(schema.get('properties', {}), defs),
            'required': schema.get('required', []),
            'additionalProperties': False,
        }

        return result

    @staticmethod
    def _resolve_refs_in_object(obj: Any, defs_map: Dict[str, Any]) -> Any:
        """Recursively resolve references in an object."""
        if isinstance(obj, dict):
            if '$ref' in obj:
                return ToolSchema._resolve_single_ref(obj, defs_map)
            else:
                return {k: ToolSchema._resolve_refs_in_object(v, defs_map) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [ToolSchema._resolve_refs_in_object(item, defs_map) for item in obj]
        else:
            return obj

    @staticmethod
    def _resolve_single_ref(ref_obj: Dict[str, Any], defs_map: Dict[str, Any]) -> Any:
        """Resolve a single $ref object."""
        ref_path = ref_obj['$ref']
        if ref_path.startswith('#/$defs/'):
            def_name = ref_path.split('/')[-1]
            if def_name in defs_map:
                resolved = defs_map[def_name].copy()
                return ToolSchema._resolve_refs_in_object(resolved, defs_map)
        return ref_obj

    @staticmethod
    def openai_schema(tool_class: type) -> Dict[str, Any]:
        """Generate OpenAI compatible schema."""
        return {
            'type': 'function',
            'function': {
                'name': tool_class.get_name(),
                'description': tool_class.get_desc(),
                'parameters': ToolSchema.get_parameters(tool_class),
            },
        }

    @staticmethod
    def anthropic_schema(tool_class: type) -> Dict[str, Any]:
        """Generate Anthropic compatible schema."""
        return {
            'name': tool_class.get_name(),
            'description': tool_class.get_desc(),
            'input_schema': ToolSchema.get_parameters(tool_class),
        }

    @staticmethod
    def calculate_tokens(tool_class: type) -> int:
        """Calculate total tokens for tool description and parameters."""
        cache_attr = '_cached_tokens'
        if hasattr(tool_class, cache_attr):
            return getattr(tool_class, cache_attr)

        desc_tokens = count_tokens(tool_class.get_desc())
        params = ToolSchema.get_parameters(tool_class)
        params_text = json.dumps(params, ensure_ascii=False)
        params_tokens = count_tokens(params_text)

        total_tokens = desc_tokens + params_tokens
        setattr(tool_class, cache_attr, total_tokens)
        return total_tokens


class ToolExecutor:
    """Handles tool execution with timeout and interrupt support."""

    @staticmethod
    async def execute_async(tool_class: type, tool_call: ToolCall, instance: 'ToolInstance'):
        """Execute tool asynchronously with proper error handling."""
        loop = asyncio.get_event_loop()
        with ThreadPoolExecutor() as executor:

            def run_with_interrupt_check():
                return tool_class.invoke(tool_call, instance)

            future = loop.run_in_executor(executor, run_with_interrupt_check)
            try:
                await asyncio.wait_for(future, timeout=tool_class.get_timeout())
            except asyncio.CancelledError:
                instance._interrupt_flag.set()
                future.cancel()
                raise
            except asyncio.TimeoutError:
                instance._interrupt_flag.set()
                future.cancel()
                instance.tool_msg.tool_call.status = 'canceled'
                instance.tool_msg.content = f"Tool '{tool_class.get_name()}' timed out after {tool_class.get_timeout()}s"


class ToolDisplayManager:
    """Manages tool execution display and UI."""

    @staticmethod
    def generate_status_text(tool_calls: List[ToolCall]) -> Text:
        """Generate status text for tool execution."""
        if len(tool_calls) == 1:
            return Text.assemble('Executing ', (ToolCall.get_display_tool_name(tool_calls[0].tool_name), ColorStyle.HIGHLIGHT.bold), ' ')
        else:
            tool_counts = {}
            for tc in tool_calls:
                tool_counts[tc.tool_name] = tool_counts.get(tc.tool_name, 0) + 1
            tool_names = [
                Text.assemble((ToolCall.get_display_tool_name(name), ColorStyle.HIGHLIGHT.bold), '*' + str(count) if count > 1 else '', ' ') for name, count in tool_counts.items()
            ]
            return Text.assemble('Executing ', *tool_names)

    @staticmethod
    def create_live_group(tool_instances: List['ToolInstance']) -> list:
        """Create the live group for display."""
        live_group = []
        for ti in tool_instances:
            live_group.append('')
            live_group.append(ti.tool_result())
        return live_group

    @staticmethod
    async def live_display(tool_instances: List['ToolInstance'], tool_calls: List[ToolCall], interrupt_handler: 'InterruptHandler'):
        try:
            status_text = ToolDisplayManager.generate_status_text(tool_calls)
            status = render_dot_status(status=status_text)

            with Live(refresh_per_second=10, console=console.console) as live:
                live_group = ToolDisplayManager.create_live_group(tool_instances)
                while any(ti.is_running() for ti in tool_instances) and not interrupt_handler.interrupted:
                    live.update(Group(*live_group, status))
                    await asyncio.sleep(0.1)
                live.update(Group(*live_group))
        except Exception as e:
            console.print(format_exception(e), style=ColorStyle.ERROR)
            raise e


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
        """Get tool parameters schema."""
        return ToolSchema.get_parameters(cls)

    @classmethod
    def tokens(cls) -> int:
        """Calculate total tokens for tool description and parameters."""
        return ToolSchema.calculate_tokens(cls)

    @classmethod
    def openai_schema(cls) -> Dict[str, Any]:
        """Generate OpenAI compatible schema."""
        return ToolSchema.openai_schema(cls)

    @classmethod
    def anthropic_schema(cls) -> Dict[str, Any]:
        """Generate Anthropic compatible schema."""
        return ToolSchema.anthropic_schema(cls)

    def __str__(self) -> str:
        return self.json_openai_schema()

    def __repr__(self) -> str:
        return self.json_openai_schema()

    @classmethod
    def json_openai_schema(cls):
        return json.dumps(cls.openai_schema())

    @classmethod
    def create_instance(cls, tool_call: ToolCall, agent_state: 'AgentState') -> 'ToolInstance':
        return ToolInstance(tool=cls, tool_call=tool_call, agent_state=agent_state)

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
        """Execute tool asynchronously with proper error handling."""
        await ToolExecutor.execute_async(cls, tool_call, instance)


class ToolInstance:
    """
    ToolInstance is the instance of a runtime tool call.
    """

    def __init__(self, tool: type[Tool], tool_call: ToolCall, agent_state: 'AgentState'):
        self.tool = tool
        self.tool_call = tool_call
        self.tool_msg: ToolMessage = ToolMessage(tool_call_id=tool_call.id, tool_call_cache=tool_call)
        self.agent_state: 'AgentState' = agent_state

        self._task: Optional[asyncio.Task] = None
        self._is_running = False
        self._is_completed = False
        self._interrupt_flag = threading.Event()
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
            self.tool_msg.set_error_msg(format_exception(e))
            self._is_completed = True
        finally:
            self._is_running = False

    def is_running(self) -> bool:
        return self._is_running and not self._is_completed

    def is_completed(self) -> bool:
        return self._is_completed

    async def wait(self):
        if self._task:
            await self._task

    def cancel(self):
        self._cancel_requested = True
        self._interrupt_flag.set()
        if self._task and not self._task.done():
            self._task.cancel()
            self._is_completed = True
            self.tool_msg.tool_call.status = 'canceled'

    def is_cancelled(self) -> bool:
        """Check if cancellation was requested."""
        return self._cancel_requested or self._interrupt_flag.is_set()

    def check_interrupt(self) -> bool:
        """Check if tool should be interrupted (for use in sync code)."""
        return self._interrupt_flag.is_set()


class ToolHandler:
    """
    ToolHandler accepts a list of tool calls.
    """

    def __init__(self, agent_state, tools: List[Tool], show_live: bool = True):
        self.agent_state: 'AgentState' = agent_state
        self.tool_dict = {tool.name: tool for tool in tools} if tools else {}
        self.show_live = show_live
        self._global_interrupt = threading.Event()

    async def handle(self, ai_message: AIMessage):
        """Handle all tool calls in the AI message."""
        if not ai_message.tool_calls or not len(ai_message.tool_calls):
            return

        parallelable_calls, non_parallelable_calls = self._categorize_tool_calls(ai_message.tool_calls)

        # Handle parallelable tools first
        await self.handle_tool_calls(parallelable_calls)

        # Handle non-parallelable tools one by one
        for tc in non_parallelable_calls:
            await self.handle_tool_calls([tc])

    def _categorize_tool_calls(self, tool_calls: Dict[str, ToolCall]) -> tuple[List[ToolCall], List[ToolCall]]:
        """Categorize tool calls into parallelable and non-parallelable."""
        parallelable_calls = []
        non_parallelable_calls = []

        for tool_call in tool_calls.values():
            if tool_call.tool_name not in self.tool_dict:
                continue
            if self.tool_dict[tool_call.tool_name].skip_in_tool_handler():
                continue
            if self.tool_dict[tool_call.tool_name].is_parallelable():
                parallelable_calls.append(tool_call)
            else:
                non_parallelable_calls.append(tool_call)

        return parallelable_calls, non_parallelable_calls

    async def handle_tool_calls(self, tool_calls: List[ToolCall]):
        """Unified method to handle both single and multiple tool calls."""
        if not tool_calls:
            return

        tool_instances = [self.tool_dict[tc.tool_name].create_instance(tc, self.agent_state) for tc in tool_calls]
        tasks = await self._start_tool_tasks(tool_instances)

        interrupted = False
        signal_handler_added = False
        interrupt_handler = InterruptHandler(tool_instances, self)

        try:
            monitor_task = None
            signal_handler_added = interrupt_handler.setup_signal_handler()
            if not signal_handler_added:
                monitor_task = asyncio.create_task(interrupt_handler.interrupt_monitor())

            if self.show_live:
                await ToolDisplayManager.live_display(tool_instances, tool_calls, interrupt_handler)

            await asyncio.gather(*tasks, return_exceptions=True)
            interrupted = interrupt_handler.interrupted

        finally:
            if signal_handler_added:
                interrupt_handler.cleanup_signal_handler()
            if monitor_task:
                monitor_task.cancel()
                try:
                    await monitor_task
                except asyncio.CancelledError:
                    pass
            self.agent_state.session.append_message(*(ti.tool_result() for ti in tool_instances))
            if interrupted:
                raise asyncio.CancelledError

    async def _start_tool_tasks(self, tool_instances: List[ToolInstance]) -> List[asyncio.Task]:
        """Start async tasks for all tool instances."""
        return [await ti.start_async() for ti in tool_instances]


class InterruptHandler:
    """Handles interrupt logic for tool execution."""

    def __init__(self, tool_instances: List[ToolInstance], tool_handler: ToolHandler):
        self.tool_instances = tool_instances
        self.tool_handler = tool_handler
        self.interrupted = False
        self._signal_handler_added = False

    def signal_handler(self, *args):
        """Handle interrupt signal."""
        self.interrupted = True
        self.tool_handler._global_interrupt.set()
        for ti in self.tool_instances:
            ti.cancel()

    def setup_signal_handler(self) -> bool:
        """Setup signal handler for SIGINT."""
        try:
            loop = asyncio.get_event_loop()
            loop.add_signal_handler(signal.SIGINT, self.signal_handler)
            self._signal_handler_added = True
            return True
        except (ValueError, NotImplementedError, OSError, RuntimeError):
            return False

    def cleanup_signal_handler(self):
        """Remove signal handler."""
        if self._signal_handler_added:
            try:
                loop = asyncio.get_event_loop()
                loop.remove_signal_handler(signal.SIGINT)
            except (ValueError, NotImplementedError, OSError):
                pass

    async def interrupt_monitor(self):
        """Monitor for interrupts when signal handler is not available."""
        while not self.interrupted and any(ti.is_running() for ti in self.tool_instances):
            try:
                if hasattr(self.tool_handler.agent_state, '_should_interrupt') and self.tool_handler.agent_state._should_interrupt():
                    self.signal_handler()
                    break
                await asyncio.sleep(0.05)
            except asyncio.CancelledError:
                break
