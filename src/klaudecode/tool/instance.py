import asyncio
import threading
from typing import TYPE_CHECKING, Optional

from ..message import ToolCall, ToolMessage
from ..utils.exception import format_exception

if TYPE_CHECKING:
    from ..agent import AgentState
    from .base import Tool


class ToolInstance:
    """
    ToolInstance is the instance of a runtime tool call.
    """

    def __init__(self, tool: type['Tool'], tool_call: ToolCall, agent_state: 'AgentState'):
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
