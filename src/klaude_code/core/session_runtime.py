from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from klaude_code.protocol import op


@dataclass(frozen=True)
class _StopSignal:
    pass


_STOP_SIGNAL = _StopSignal()


class SessionRuntime:
    def __init__(
        self,
        *,
        session_id: str,
        handle_submission: Callable[[op.Submission], Awaitable[None]],
        execution_lock: asyncio.Lock,
    ) -> None:
        self.session_id = session_id
        self.mailbox: asyncio.Queue[op.Submission | _StopSignal] = asyncio.Queue()
        self._handle_submission = handle_submission
        self._execution_lock = execution_lock
        self._worker_task: asyncio.Task[None] = asyncio.create_task(self._run_loop())

    async def enqueue(self, submission: op.Submission) -> None:
        await self.mailbox.put(submission)

    async def stop(self) -> None:
        while True:
            try:
                _ = self.mailbox.get_nowait()
                self.mailbox.task_done()
            except asyncio.QueueEmpty:
                break
        await self.mailbox.put(_STOP_SIGNAL)
        await self._worker_task

    async def _run_loop(self) -> None:
        while True:
            item = await self.mailbox.get()
            try:
                if isinstance(item, _StopSignal):
                    return
                async with self._execution_lock:
                    await self._handle_submission(item)
            finally:
                self.mailbox.task_done()
