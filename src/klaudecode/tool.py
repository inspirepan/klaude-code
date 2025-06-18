import asyncio
import json
from abc import ABC
from typing import Any, Dict, List, Optional
from concurrent.futures import ThreadPoolExecutor

from pydantic import BaseModel
from rich.console import Group
from rich.live import Live
from rich.status import Status

from .message import AIMessage, ToolCallMessage, ToolMessage
from .tui import console, INTERRUPT_TIP


class Tool(ABC):
    name: str = ""
    desc: str = ""
    parallelable: bool = True
    timeout = 60

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
            return {
                "type": "object",
                "properties": schema.get("properties", {}),
                "required": schema.get("required", [])
            }

        return {"type": "object", "properties": {}, "required": []}

    @classmethod
    def openai_schema(cls) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": cls.get_name(),
                "description": cls.get_desc(),
                "parameters": cls.get_parameters(),
            },
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
            except asyncio.TimeoutError:
                instance.tool_msg.tool_call.status = "error"
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
            self.tool_msg.tool_call.status = "success"
        except Exception as e:
            self.tool_msg.tool_call.status = "error"
            self.tool_msg.content += f"error: {str(e)}"
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

        if self.show_live:
            tool_counts = {}
            for tc in tool_calls:
                tool_counts[tc.tool_name] = tool_counts.get(tc.tool_name, 0) + 1
            status_text = "Executing " + " ".join([f"[bold]{name}[/bold]*{count}" for name, count in tool_counts.items()]) + "... " + INTERRUPT_TIP
            status = Status(status_text, spinner="dots", spinner_style="gray")
            with Live(refresh_per_second=10, console=console.console) as live:
                while any(ti.is_running() for ti in tool_instances):
                    tool_results = [ti.tool_result() for ti in tool_instances]
                    live.update(Group(*tool_results, status))
                    await asyncio.sleep(0.1)
                live.update(Group(*[ti.tool_result() for ti in tool_instances]))

        await asyncio.gather(*tasks, return_exceptions=True)
        self.agent.append_message(*[ti.tool_result() for ti in tool_instances], print_msg=False)

    async def handle_single_tool_call(self, tool_call: ToolCallMessage):
        tool_instance = self.tool_dict[tool_call.tool_name].create_instance(tool_call, self.agent)
        task = await tool_instance.start_async()

        if self.show_live:
            status_text = f"Executing [bold]{tool_call.tool_name}[/bold]...  {INTERRUPT_TIP}"
            status = Status(status_text, spinner="dots", spinner_style="gray")
            with Live(refresh_per_second=10, console=console.console) as live:
                while tool_instance.is_running():
                    live.update(Group(tool_instance.tool_result(), status))
                    await asyncio.sleep(0.1)
                live.update(tool_instance.tool_result())

        await task
        self.agent.append_message(tool_instance.tool_result(), print_msg=False)
