from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from klaude_code.core.control.session_runtime import SessionRuntime, SessionRuntimeConfig, SessionRuntimeSnapshot
from klaude_code.core.control.user_interaction import PendingUserInteractionRequest
from klaude_code.protocol import op, user_interaction

GLOBAL_RUNTIME_ID = "__runtime_global__"


@dataclass
class _PendingInteractionState:
    request: PendingUserInteractionRequest
    future: asyncio.Future[user_interaction.UserInteractionResponse]


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
        self._request_queue: asyncio.Queue[PendingUserInteractionRequest] = asyncio.Queue()
        self._pending_interactions: dict[str, _PendingInteractionState] = {}

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
        if request.request_id in self._pending_interactions:
            raise RuntimeError(f"Duplicate user interaction request id: {request.request_id}")

        runtime = self._ensure_runtime(request.session_id)
        loop = asyncio.get_running_loop()
        future: asyncio.Future[user_interaction.UserInteractionResponse] = loop.create_future()
        self._pending_interactions[request.request_id] = _PendingInteractionState(request=request, future=future)

        def _on_done(_future: asyncio.Future[user_interaction.UserInteractionResponse]) -> None:
            self._finalize_user_interaction_request(request.request_id)

        future.add_done_callback(_on_done)
        runtime.mark_request_pending(request)
        self._request_queue.put_nowait(request)
        return await future

    def respond_user_interaction(
        self,
        *,
        request_id: str,
        session_id: str,
        response: user_interaction.UserInteractionResponse,
    ) -> None:
        pending = self._pending_interactions.get(request_id)
        if pending is None:
            raise ValueError("No pending user interaction")
        if pending.request.session_id != session_id:
            raise ValueError("Session mismatch for pending user interaction")
        if response.status == "submitted" and response.payload is None:
            raise ValueError("Submitted response must include payload")

        if not pending.future.done():
            pending.future.set_result(response)

    def cancel_pending_interactions(self, *, session_id: str | None = None) -> bool:
        cancelled = False
        for request_id, pending in list(self._pending_interactions.items()):
            if session_id is not None and pending.request.session_id != session_id:
                continue
            cancelled = True
            if pending.future.done():
                self._finalize_user_interaction_request(request_id)
                continue
            pending.future.cancel()
        return cancelled

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

    def mark_request_state(self, *, request: PendingUserInteractionRequest, is_pending: bool) -> None:
        runtime = self._runtimes.get(request.session_id)
        if runtime is None:
            return
        if is_pending:
            runtime.mark_request_pending(request)
            self._request_queue.put_nowait(request)
            return
        runtime.mark_request_resolved(request.request_id)

    def mark_child_task_state(self, *, session_id: str, task_id: str, is_active: bool) -> None:
        runtime = self._runtimes.get(session_id)
        if runtime is None:
            return
        if is_active:
            runtime.mark_child_task_started(task_id)
            return
        runtime.mark_child_task_completed(task_id)

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
        self.cancel_pending_interactions(session_id=None)
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

        self.cancel_pending_interactions(session_id=session_id)

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

    def _finalize_user_interaction_request(self, request_id: str) -> None:
        pending = self._pending_interactions.pop(request_id, None)
        if pending is None:
            return
        runtime = self._runtimes.get(pending.request.session_id)
        if runtime is None:
            return
        runtime.mark_request_resolved(request_id)


def _should_preempt_control(runtime: SessionRuntime, operation: op.Operation) -> bool:
    if not runtime.has_active_root_task():
        return False
    return isinstance(operation, op.InterruptOperation | op.UserInteractionRespondOperation)
