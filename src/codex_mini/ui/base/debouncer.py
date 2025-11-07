import asyncio
from typing import Awaitable, Callable, Optional


class Debouncer:
    """Debouncing mechanism"""

    def __init__(self, interval: float, callback: Callable[[], Awaitable[None]]):
        """
        Initialize debouncer

        Args:
            interval: Debounce interval in seconds
            callback: Async callback function to execute after debouncing
        """
        self.interval = interval
        self.callback = callback
        self._task: Optional[asyncio.Task[None]] = None

    def cancel(self) -> None:
        """Cancel current debounce task"""
        if self._task is not None and not self._task.done():
            self._task.cancel()
        self._task = None

    def schedule(self) -> None:
        """Schedule debounce task"""
        self.cancel()
        self._task = asyncio.create_task(self._debounced_execute())

    async def _debounced_execute(self) -> None:
        """Execute debounced callback function"""
        try:
            await asyncio.sleep(self.interval)
            await self.callback()
        except asyncio.CancelledError:
            return

    async def flush(self) -> None:
        """Immediately execute debounce task (without waiting)"""
        self.cancel()
        await self.callback()
