from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from klaude_code.core.session_runtime import SessionRuntime, SessionRuntimeConfig, SessionRuntimeSnapshot
from klaude_code.core.user_interaction import PendingUserInteractionRequest
from klaude_code.protocol import op

GLOBAL_RUNTIME_ID = "__runtime_global__"


class RuntimeHub:
    def __init__(
        self,
        *,
        handle_operation: Callable[[op.Operation], Awaitable[None]],
        reject_operation: Callable[[op.Operation, str | None], Awaitable[None]],
        control_burst_quota: int = 8,
    ) -> None:
        self._handle_operation = handle_operation
        self._reject_operation = reject_operation
        self._control_burst_quota = control_burst_quota
        self._execution_lock = asyncio.Lock()
        self._runtimes: dict[str, SessionRuntime] = {}
        self._operation_runtime_ids: dict[str, str] = {}
        self._request_queue: asyncio.Queue[PendingUserInteractionRequest] = asyncio.Queue()

    async def submit(self, operation: op.Operation) -> None:
        runtime_id = self._resolve_runtime_id(operation)
        runtime = self._runtimes.get(runtime_id)
        if runtime is None:
            runtime = SessionRuntime(
                session_id=runtime_id,
                handle_operation=self._handle_operation,
                reject_operation=self._reject_operation,
                execution_lock=self._execution_lock,
                control_burst_quota=self._control_burst_quota,
            )
            self._runtimes[runtime_id] = runtime
        self._operation_runtime_ids[operation.id] = runtime_id
        await runtime.enqueue(operation)

    def mark_operation_completed(self, operation_id: str) -> None:
        runtime_id = self._operation_runtime_ids.pop(operation_id, None)
        if runtime_id is None:
            return
        runtime = self._runtimes.get(runtime_id)
        if runtime is None:
            return
        runtime.mark_operation_completed(operation_id)

    def mark_request_state(self, *, request: PendingUserInteractionRequest, is_pending: bool) -> None:
        runtime = self._runtimes.get(request.session_id)
        if runtime is None:
            return
        if is_pending:
            runtime.mark_request_pending(request)
            self._request_queue.put_nowait(request)
            return
        runtime.mark_request_resolved(request.request_id)

    async def wait_next_request(self) -> PendingUserInteractionRequest:
        while True:
            request = await self._request_queue.get()
            if self._is_request_pending(request):
                return request

    def _is_request_pending(self, request: PendingUserInteractionRequest) -> bool:
        runtime = self._runtimes.get(request.session_id)
        if runtime is None:
            return False
        return runtime.has_pending_request(request.request_id)

    def pending_request_count(self, session_id: str) -> int:
        runtime = self._runtimes.get(session_id)
        if runtime is None:
            return 0
        return runtime.pending_request_count()

    def apply_operation_effect(self, operation: op.Operation) -> None:
        session_id = getattr(operation, "session_id", None)
        if session_id is None:
            return
        runtime = self._runtimes.get(session_id)
        if runtime is None:
            return
        runtime.apply_operation_effect(operation)

    def config_snapshot(self, session_id: str) -> SessionRuntimeConfig | None:
        runtime = self._runtimes.get(session_id)
        if runtime is None:
            return None
        return runtime.config_snapshot()

    def idle_runtime_ids(self) -> list[str]:
        return [runtime_id for runtime_id, runtime in self._runtimes.items() if runtime.is_idle()]

    def snapshot(self, session_id: str) -> SessionRuntimeSnapshot | None:
        runtime = self._runtimes.get(session_id)
        if runtime is None:
            return None
        return runtime.snapshot()

    def all_snapshots(self) -> list[SessionRuntimeSnapshot]:
        return [runtime.snapshot() for runtime in self._runtimes.values()]

    async def stop(self) -> None:
        runtimes = list(self._runtimes.values())
        self._runtimes.clear()
        self._operation_runtime_ids.clear()
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
