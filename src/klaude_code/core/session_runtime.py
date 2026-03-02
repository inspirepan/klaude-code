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
        reject_submission: Callable[[op.Submission, str | None], Awaitable[None]],
        execution_lock: asyncio.Lock,
    ) -> None:
        self.session_id = session_id
        self.mailbox: asyncio.Queue[op.Submission | _StopSignal] = asyncio.Queue()
        self._handle_submission = handle_submission
        self._reject_submission = reject_submission
        self._execution_lock = execution_lock
        self._active_root_submission_id: str | None = None
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

    def mark_submission_completed(self, submission_id: str) -> None:
        if self._active_root_submission_id == submission_id:
            self._active_root_submission_id = None

    async def _run_loop(self) -> None:
        while True:
            item = await self.mailbox.get()
            try:
                if isinstance(item, _StopSignal):
                    return
                if _is_root_operation(item.operation) and self._active_root_submission_id is not None:
                    await self._reject_submission(item, self._active_root_submission_id)
                    continue
                if _is_root_operation(item.operation):
                    self._active_root_submission_id = item.id
                async with self._execution_lock:
                    await self._handle_submission(item)
            finally:
                self.mailbox.task_done()


def _is_root_operation(operation: op.Operation) -> bool:
    return isinstance(
        operation,
        op.RunAgentOperation | op.RunBashOperation | op.ContinueAgentOperation | op.CompactSessionOperation,
    )
