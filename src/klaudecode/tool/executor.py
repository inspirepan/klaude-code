import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING

from ..message import ToolCall

if TYPE_CHECKING:
    from .instance import ToolInstance


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
