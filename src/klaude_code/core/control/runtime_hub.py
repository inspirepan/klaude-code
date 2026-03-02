from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable

from klaude_code.core.control.session_runtime import SessionRuntime, SessionRuntimeConfig, SessionRuntimeSnapshot
from klaude_code.core.control.user_interaction import PendingUserInteractionRequest
from klaude_code.protocol import op, user_interaction

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
        self._runtimes: dict[str, SessionRuntime] = {}
        self._operation_runtime_ids: dict[str, str] = {}
        self._completion_events: dict[str, asyncio.Event] = {}

    async def submit(self, operation: op.Operation) -> None:
        if operation.id in self._completion_events:
            raise RuntimeError(f"Operation already registered: {operation.id}")

        self._completion_events[operation.id] = asyncio.Event()

        runtime_id = self._resolve_runtime_id(operation)
        runtime = self._ensure_runtime(runtime_id)
        self._operation_runtime_ids[operation.id] = runtime_id

        if _should_preempt_control(runtime, operation):
            await runtime.run_control_preemptive(operation)
            return

        await runtime.enqueue(operation)

    async def request_user_interaction(
        self,
        request: PendingUserInteractionRequest,
    ) -> user_interaction.UserInteractionResponse:
        runtime = self._ensure_runtime(request.session_id)
        future = runtime.open_pending_interaction(request)
        return await future

    def respond_user_interaction(
        self,
        *,
        request_id: str,
        session_id: str,
        response: user_interaction.UserInteractionResponse,
    ) -> None:
        runtime = self._runtimes.get(session_id)
        if runtime is None:
            raise ValueError("No pending user interaction")
        runtime.resolve_pending_interaction(request_id=request_id, session_id=session_id, response=response)

    def cancel_pending_interactions_with_requests(
        self,
        *,
        session_id: str | None = None,
    ) -> list[PendingUserInteractionRequest]:
        cancelled: list[PendingUserInteractionRequest] = []
        for runtime_id, runtime in self._runtimes.items():
            if session_id is not None and runtime_id != session_id:
                continue
            cancelled.extend(runtime.cancel_pending_interactions())
        return cancelled

    def cancel_pending_interactions(self, *, session_id: str | None = None) -> bool:
        return bool(self.cancel_pending_interactions_with_requests(session_id=session_id))

    def mark_operation_completed(self, operation_id: str) -> None:
        completion_event = self._completion_events.get(operation_id)
        if completion_event is not None:
            completion_event.set()

        runtime_id = self._operation_runtime_ids.pop(operation_id, None)
        if runtime_id is None:
            return
        runtime = self._runtimes.get(runtime_id)
        if runtime is None:
            return
        runtime.mark_operation_completed(operation_id)

    async def wait_for(self, operation_id: str) -> None:
        event = self._completion_events.get(operation_id)
        if event is not None:
            await event.wait()
            self._completion_events.pop(operation_id, None)

    def bind_root_task(self, *, operation_id: str, task_id: str) -> None:
        runtime_id = self._operation_runtime_ids.get(operation_id)
        if runtime_id is None:
            return
        runtime = self._runtimes.get(runtime_id)
        if runtime is None:
            return
        runtime.bind_root_task(operation_id=operation_id, task_id=task_id)

    def mark_child_task_state(self, *, session_id: str, task_id: str, is_active: bool) -> None:
        runtime = self._runtimes.get(session_id)
        if runtime is None:
            return
        if is_active:
            runtime.mark_child_task_started(task_id)
            return
        runtime.mark_child_task_completed(task_id)

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
        self.cancel_pending_interactions_with_requests(session_id=None)
        for completion_event in self._completion_events.values():
            completion_event.set()
        self._completion_events.clear()
        runtimes = list(self._runtimes.values())
        self._runtimes.clear()
        self._operation_runtime_ids.clear()
        for runtime in runtimes:
            await runtime.stop()

    async def close_session(self, session_id: str, *, force: bool = False) -> bool:
        if session_id == GLOBAL_RUNTIME_ID:
            return False
        runtime = self._runtimes.get(session_id)
        if runtime is None:
            return False
        if not force and not runtime.is_idle():
            return False

        runtime.cancel_pending_interactions()

        self._runtimes.pop(session_id, None)
        for operation_id, runtime_id in list(self._operation_runtime_ids.items()):
            if runtime_id == session_id:
                self._operation_runtime_ids.pop(operation_id, None)
                completion_event = self._completion_events.get(operation_id)
                if completion_event is not None:
                    completion_event.set()

        await runtime.stop()
        return True

    async def reclaim_idle_runtimes(self, *, idle_for_seconds: float = 0.0) -> list[str]:
        reclaimed: list[str] = []
        now = time.monotonic()
        for session_id in list(self._runtimes):
            if session_id == GLOBAL_RUNTIME_ID:
                continue
            runtime = self._runtimes.get(session_id)
            if runtime is None:
                continue
            idle_seconds = runtime.idle_for_seconds(now)
            if idle_seconds is None or idle_seconds < idle_for_seconds:
                continue
            closed = await self.close_session(session_id, force=False)
            if closed:
                reclaimed.append(session_id)
        return reclaimed

    def has_runtime(self, runtime_id: str) -> bool:
        return runtime_id in self._runtimes

    def _resolve_runtime_id(self, operation: op.Operation) -> str:
        session_id = getattr(operation, "session_id", None)
        if session_id is not None:
            return session_id
        if isinstance(operation, op.InterruptOperation) and operation.target_session_id is not None:
            return operation.target_session_id
        if isinstance(operation, op.CloseSessionOperation):
            return GLOBAL_RUNTIME_ID
        return GLOBAL_RUNTIME_ID

    def _ensure_runtime(self, runtime_id: str) -> SessionRuntime:
        runtime = self._runtimes.get(runtime_id)
        if runtime is not None:
            return runtime

        runtime = SessionRuntime(
            session_id=runtime_id,
            handle_operation=self._handle_operation,
            reject_operation=self._reject_operation,
            control_burst_quota=self._control_burst_quota,
        )
        self._runtimes[runtime_id] = runtime
        return runtime

def _should_preempt_control(runtime: SessionRuntime, operation: op.Operation) -> bool:
    if not runtime.has_active_root_task():
        return False
    return isinstance(operation, op.InterruptOperation | op.UserInteractionRespondOperation)
