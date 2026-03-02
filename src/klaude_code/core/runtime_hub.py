from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from klaude_code.core.session_runtime import SessionRuntime
from klaude_code.protocol import op

GLOBAL_RUNTIME_ID = "__runtime_global__"


class RuntimeHub:
    def __init__(self, *, handle_submission: Callable[[op.Submission], Awaitable[None]]) -> None:
        self._handle_submission = handle_submission
        self._execution_lock = asyncio.Lock()
        self._runtimes: dict[str, SessionRuntime] = {}

    async def submit(self, submission: op.Submission) -> None:
        runtime_id = self._resolve_runtime_id(submission.operation)
        runtime = self._runtimes.get(runtime_id)
        if runtime is None:
            runtime = SessionRuntime(
                session_id=runtime_id,
                handle_submission=self._handle_submission,
                execution_lock=self._execution_lock,
            )
            self._runtimes[runtime_id] = runtime
        await runtime.enqueue(submission)

    async def stop(self) -> None:
        runtimes = list(self._runtimes.values())
        self._runtimes.clear()
        for runtime in runtimes:
            await runtime.stop()

    def has_runtime(self, runtime_id: str) -> bool:
        return runtime_id in self._runtimes

    def _resolve_runtime_id(self, operation: op.Operation) -> str:
        session_id = getattr(operation, "session_id", None)
        if session_id is not None:
            return session_id
        if isinstance(operation, op.InterruptOperation) and operation.target_session_id is not None:
            return operation.target_session_id
        return GLOBAL_RUNTIME_ID
