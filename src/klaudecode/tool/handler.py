import asyncio
import signal
import threading
from typing import Dict, List

from ..message import AIMessage, ToolCall
from ..tui import ColorStyle, console, render_suffix
from .base import Tool
from .display import ToolDisplayManager
from .instance import ToolInstance


class ToolHandler:
    """
    ToolHandler accepts a list of tool calls.
    """

    def __init__(self, agent_state, show_live: bool = True):
        self.agent_state = agent_state
        self.show_live = show_live
        self._global_interrupt = threading.Event()

    def _get_tool_dict(self) -> Dict[str, Tool]:
        """Get current tool dictionary, dynamically refreshed from agent_state.all_tools"""
        tools = self.agent_state.all_tools
        return {tool.name: tool for tool in tools} if tools else {}

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
        tool_dict = self._get_tool_dict()

        for tool_call in tool_calls.values():
            if tool_call.tool_name not in tool_dict:
                console.print(render_suffix(f'Tool {tool_call.tool_name} not found', style=ColorStyle.ERROR))
                continue
            if tool_dict[tool_call.tool_name].skip_in_tool_handler():
                continue
            if tool_dict[tool_call.tool_name].is_parallelable():
                parallelable_calls.append(tool_call)
            else:
                non_parallelable_calls.append(tool_call)

        return parallelable_calls, non_parallelable_calls

    async def handle_tool_calls(self, tool_calls: List[ToolCall]):
        """Unified method to handle both single and multiple tool calls."""
        if not tool_calls:
            return

        tool_dict = self._get_tool_dict()
        tool_instances = [tool_dict[tc.tool_name].create_instance(tc, self.agent_state) for tc in tool_calls]
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
