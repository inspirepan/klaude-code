import asyncio
import json
import signal
from abc import ABC
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional

from pydantic import BaseModel
from rich.columns import Columns
from rich.console import Group
from rich.live import Live
from rich.status import Status

from .message import AIMessage, ToolCallMessage, ToolMessage
from .tui import INTERRUPT_TIP, console


class Tool(ABC):
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
    def get_parameters(cls) -> Dict[str, Any]:
        if hasattr(cls, 'parameters'):
            return cls.parameters

        if hasattr(cls, 'Input') and issubclass(cls.Input, BaseModel):
            schema = cls.Input.model_json_schema()
            return cls._resolve_schema_refs(schema)

        return {'type': 'object', 'properties': {}, 'required': []}

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
    def create_instance(cls, tool_call: ToolCallMessage, parent_agent) -> 'ToolInstance':
        return ToolInstance(tool=cls, tool_call=tool_call, parent_agent=parent_agent)

    @classmethod
    def parse_input_args(cls, tool_call: ToolCallMessage) -> Optional[BaseModel]:
        if hasattr(cls, 'Input') and issubclass(cls.Input, BaseModel):
            args_dict = json.loads(tool_call.tool_args)
            input_inst = cls.Input(**args_dict)
            tool_call.nice_args = str(input_inst)
            return input_inst
        return None

    @classmethod
    def invoke(cls, tool_call: ToolCallMessage, instance: 'ToolInstance'):
        raise NotImplementedError

    @classmethod
    async def invoke_async(cls, tool_call: ToolCallMessage, instance: 'ToolInstance'):
        loop = asyncio.get_event_loop()
        with ThreadPoolExecutor() as executor:
            future = loop.run_in_executor(executor, cls.invoke, tool_call, instance)
            try:
                await asyncio.wait_for(future, timeout=cls.get_timeout())
            except asyncio.CancelledError:
                future.cancel()
                raise
            except asyncio.TimeoutError:
                future.cancel()
                instance.tool_msg.tool_call.status = 'canceled'
                instance.tool_msg.content = f"Tool '{cls.get_name()}' timed out after {cls.get_timeout()}s"


class ToolInstance:
    def __init__(self, tool: type[Tool], tool_call: ToolCallMessage, parent_agent):
        self.tool = tool
        self.tool_call = tool_call
        self.tool_msg: ToolMessage = ToolMessage(tool_call=tool_call)
        self.parent_agent = parent_agent

        self._task: Optional[asyncio.Task] = None
        self._is_running = False
        self._is_completed = False

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
            self.tool_msg.tool_call.status = 'success'
        except asyncio.CancelledError:
            self._is_completed = True
            raise
        except Exception as e:
            self.tool_msg.tool_call.status = 'error'
            self.tool_msg.content += f'error: {str(e)}'
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
        if self._task and not self._task.done():
            self._task.cancel()
            self._is_completed = True
            self.tool_msg.tool_call.status = 'canceled'


class ToolHandler:
    def __init__(self, agent, tools: List[Tool], show_live: bool = True):
        self.agent = agent
        self.tool_dict = {tool.name: tool for tool in tools} if tools else {}
        self.show_live = show_live

    async def handle(self, ai_message: AIMessage):
        if not ai_message.tool_calls or not len(ai_message.tool_calls):
            return

        parallelable_tool_calls = []
        non_parallelable_tool_calls = []
        for tool_call in ai_message.tool_calls.values():
            if tool_call.tool_name not in self.tool_dict:
                pass
            if self.tool_dict[tool_call.tool_name].is_parallelable():
                parallelable_tool_calls.append(tool_call)
            else:
                non_parallelable_tool_calls.append(tool_call)

        await self.handle_parallel_tool_call(parallelable_tool_calls)

        for tc in non_parallelable_tool_calls:
            await self.handle_single_tool_call(tc)

    async def handle_parallel_tool_call(self, tool_calls: List[ToolCallMessage]):
        if not tool_calls:
            return

        tool_instances = [self.tool_dict[tc.tool_name].create_instance(tc, self.agent) for tc in tool_calls]
        tasks = [await ti.start_async() for ti in tool_instances]

        interrupted = False
        signal_handler_added = False

        def signal_handler():
            nonlocal interrupted
            interrupted = True
            for ti in tool_instances:
                ti.cancel()

        try:
            try:
                loop = asyncio.get_event_loop()
                loop.add_signal_handler(signal.SIGINT, signal_handler)
                signal_handler_added = True
            except (ValueError, NotImplementedError, OSError, RuntimeError):
                # Signal handling not available in this context (e.g., subthread)
                pass

            if self.show_live:
                tool_counts = {}
                for tc in tool_calls:
                    tool_counts[tc.tool_name] = tool_counts.get(tc.tool_name, 0) + 1
                status_text = 'Executing ' + ' '.join([f'[bold]{name}[/bold]*{count}' for name, count in tool_counts.items()]) + '... ' + INTERRUPT_TIP
                status = Status(status_text, spinner='dots', spinner_style='gray')
                with Live(refresh_per_second=10, console=console.console) as live:
                    while any(ti.is_running() for ti in tool_instances) and not interrupted:
                        tool_results = [ti.tool_result() for ti in tool_instances]
                        live.update(Columns([*tool_results, status], equal=True, expand=False))
                        await asyncio.sleep(0.1)
                    live.update(
                        Columns(
                            [ti.tool_result() for ti in tool_instances],
                            equal=True,
                            expand=False,
                        )
                    )

            await asyncio.gather(*tasks, return_exceptions=True)

        finally:
            if signal_handler_added:
                try:
                    loop.remove_signal_handler(signal.SIGINT)
                except (ValueError, NotImplementedError, OSError):
                    pass
            self.agent.append_message(*[ti.tool_result() for ti in tool_instances], print_msg=False)
            if interrupted:
                raise asyncio.CancelledError

    async def handle_single_tool_call(self, tool_call: ToolCallMessage):
        tool_instance = self.tool_dict[tool_call.tool_name].create_instance(tool_call, self.agent)
        task = await tool_instance.start_async()

        interrupted = False
        signal_handler_added = False

        def signal_handler():
            nonlocal interrupted
            interrupted = True
            tool_instance.cancel()

        try:
            try:
                loop = asyncio.get_event_loop()
                loop.add_signal_handler(signal.SIGINT, signal_handler)
                signal_handler_added = True
            except (ValueError, NotImplementedError, OSError, RuntimeError):
                # Signal handling not available in this context (e.g., subthread)
                pass

            if self.show_live:
                status_text = f'Executing [bold]{tool_call.tool_name}[/bold]...  {INTERRUPT_TIP}'
                status = Status(status_text, spinner='dots', spinner_style='gray')
                with Live(refresh_per_second=10, console=console.console) as live:
                    while tool_instance.is_running() and not interrupted:
                        live.update(Group(tool_instance.tool_result(), status))
                        await asyncio.sleep(0.1)
                    live.update(tool_instance.tool_result())

            await task

        finally:
            if signal_handler_added:
                try:
                    loop.remove_signal_handler(signal.SIGINT)
                except (ValueError, NotImplementedError, OSError):
                    pass

            self.agent.append_message(tool_instance.tool_result(), print_msg=False)
            if interrupted:
                raise asyncio.CancelledError
