from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal

from klaude_code.core.control.session_actor import (
    RuntimeTaskHandle,
    SessionActor,
    SessionActorSnapshot,
    SessionConfig,
)
from klaude_code.core.control.user_interaction import PendingUserInteractionRequest
from klaude_code.log import DebugType, log_debug
from klaude_code.protocol import op, user_interaction


@dataclass(frozen=True)
class OperationLifecycleHooks:
    on_operation_accepted: Callable[[op.Operation], Awaitable[None]]
    on_operation_finished: Callable[
        [op.Operation, Literal["completed", "rejected", "failed"], str | None],
        Awaitable[None],
    ]


class SessionRegistry:
    def __init__(
        self,
        *,
        handle_operation: Callable[[op.Operation], Awaitable[None]],
        reject_operation: Callable[[op.Operation, str | None], Awaitable[None]],
        control_burst_quota: int = 8,
        operation_lifecycle_hooks: OperationLifecycleHooks | None = None,
    ) -> None:
        self._handle_operation = handle_operation
        self._reject_operation = reject_operation
        self._control_burst_quota = control_burst_quota
        self._operation_lifecycle_hooks = operation_lifecycle_hooks
        self._session_actors: dict[str, SessionActor] = {}
        self._operation_runtime_ids: dict[str, str] = {}
        self._background_tasks: set[asyncio.Task[None]] = set()

    async def submit(self, operation: op.Operation) -> None:
        if operation.id in self._operation_runtime_ids:
            raise RuntimeError(f"Operation already registered: {operation.id}")

        runtime_id = self._resolve_runtime_id(operation)
        runtime = self._ensure_session_actor(runtime_id)
        self._operation_runtime_ids[operation.id] = runtime_id
        log_debug(
            f"[{runtime_id}] submit [{operation.type.value}] op={operation.id[:8]}",
            debug_type=DebugType.OPERATION,
        )
        await self._emit_operation_accepted(operation)

        if _should_preempt_control(runtime, operation):
            log_debug(
                f"[{runtime_id}] preempt [{operation.type.value}] op={operation.id[:8]}",
                debug_type=DebugType.OPERATION,
            )
            await runtime.run_control_preemptive(operation)
            return

        await runtime.enqueue(operation)

    async def request_user_interaction(
        self,
        request: PendingUserInteractionRequest,
    ) -> user_interaction.UserInteractionResponse:
        runtime = self._ensure_session_actor(request.session_id)
        future = runtime.open_pending_interaction(request)
        return await future

    def respond_user_interaction(
        self,
        *,
        request_id: str,
        session_id: str,
        response: user_interaction.UserInteractionResponse,
    ) -> None:
        runtime = self._session_actors.get(session_id)
        if runtime is None:
            raise ValueError("No pending user interaction")
        runtime.resolve_pending_interaction(request_id=request_id, session_id=session_id, response=response)

    def cancel_pending_interactions_with_requests(
        self,
        *,
        session_id: str | None = None,
    ) -> list[PendingUserInteractionRequest]:
        cancelled: list[PendingUserInteractionRequest] = []
        for runtime_id, runtime in self._session_actors.items():
            if session_id is not None and runtime_id != session_id:
                continue
            cancelled.extend(runtime.cancel_pending_interactions())
        return cancelled

    def cancel_pending_interactions(self, *, session_id: str | None = None) -> bool:
        return bool(self.cancel_pending_interactions_with_requests(session_id=session_id))

    def mark_operation_completed(self, operation_id: str) -> None:
        runtime_id = self._operation_runtime_ids.pop(operation_id, None)
        if runtime_id is None:
            return
        runtime = self._session_actors.get(runtime_id)
        if runtime is None:
            return
        runtime.mark_operation_completed(operation_id)

    def bind_root_task(self, *, operation_id: str, task_id: str) -> None:
        runtime_id = self._operation_runtime_ids.get(operation_id)
        if runtime_id is None:
            return
        runtime = self._session_actors.get(runtime_id)
        if runtime is None:
            return
        runtime.bind_root_task(operation_id=operation_id, task_id=task_id)

    def mark_child_task_state(self, *, session_id: str, task_id: str, is_active: bool) -> None:
        runtime = self._session_actors.get(session_id)
        if runtime is None:
            return
        if is_active:
            runtime.mark_child_task_started(task_id)
            return
        runtime.mark_child_task_completed(task_id)

    def pending_request_count(self, session_id: str) -> int:
        runtime = self._session_actors.get(session_id)
        if runtime is None:
            return 0
        return runtime.pending_request_count()

    def apply_operation_effect(self, operation: op.Operation) -> None:
        session_id = getattr(operation, "session_id", None)
        if session_id is None:
            return
        runtime = self._session_actors.get(session_id)
        if runtime is None:
            return
        runtime.apply_operation_effect(operation)

    def config_snapshot(self, session_id: str) -> SessionConfig | None:
        runtime = self._session_actors.get(session_id)
        if runtime is None:
            return None
        return runtime.config_snapshot()

    def idle_runtime_ids(self) -> list[str]:
        return [runtime_id for runtime_id, runtime in self._session_actors.items() if runtime.is_idle()]

    def snapshot(self, session_id: str) -> SessionActorSnapshot | None:
        runtime = self._session_actors.get(session_id)
        if runtime is None:
            return None
        return runtime.snapshot()

    def all_snapshots(self) -> list[SessionActorSnapshot]:
        return [runtime.snapshot() for runtime in self._session_actors.values()]

    async def stop(self) -> None:
        self.cancel_pending_interactions_with_requests(session_id=None)

        tasks_to_await: list[asyncio.Task[None]] = []
        for task in list(self._background_tasks):
            if task.done():
                continue
            task.cancel()
            tasks_to_await.append(task)
        if tasks_to_await:
            await asyncio.gather(*tasks_to_await, return_exceptions=True)
        self._background_tasks.clear()

        runtimes = list(self._session_actors.values())
        self._session_actors.clear()
        self._operation_runtime_ids.clear()
        for runtime in runtimes:
            await runtime.stop()

    async def close_session(self, session_id: str, *, force: bool = False) -> bool:
        runtime = self._session_actors.get(session_id)
        if runtime is None:
            return False
        if not force and not runtime.is_idle():
            return False

        runtime.cancel_pending_interactions()

        self._session_actors.pop(session_id, None)
        for operation_id, runtime_id in list(self._operation_runtime_ids.items()):
            if runtime_id == session_id:
                self._operation_runtime_ids.pop(operation_id, None)

        await runtime.stop()
        return True

    async def reclaim_idle_sessions(
        self,
        *,
        idle_for_seconds: float = 0.0,
        exclude: set[str] | None = None,
    ) -> list[str]:
        reclaimed: list[str] = []
        now = time.monotonic()
        for session_id in list(self._session_actors):
            if exclude and session_id in exclude:
                continue
            runtime = self._session_actors.get(session_id)
            if runtime is None:
                continue
            idle_seconds = runtime.idle_for_seconds(now)
            if idle_seconds is None or idle_seconds < idle_for_seconds:
                continue
            closed = await self.close_session(session_id, force=False)
            if closed:
                reclaimed.append(session_id)
        return reclaimed

    def has_session_actor(self, runtime_id: str) -> bool:
        return runtime_id in self._session_actors

    def ensure_session_actor(self, session_id: str) -> SessionActor:
        return self._ensure_session_actor(session_id)

    def get_session_actor(self, session_id: str) -> SessionActor | None:
        return self._session_actors.get(session_id)

    def get_session_actor_for_operation(self, operation_id: str) -> SessionActor | None:
        runtime_id = self._operation_runtime_ids.get(operation_id)
        if runtime_id is None:
            return None
        return self._session_actors.get(runtime_id)

    def list_session_actors(self) -> list[SessionActor]:
        return list(self._session_actors.values())

    def register_task(
        self,
        *,
        session_id: str,
        operation_id: str,
        task_id: str,
        task: asyncio.Task[None],
    ) -> None:
        runtime = self._session_actors.get(session_id)
        if runtime is None:
            raise RuntimeError(f"Missing runtime for session: {session_id}")
        runtime.register_task(operation_id=operation_id, task_id=task_id, task=task)

    def remove_task(self, *, session_id: str, task_id: str) -> None:
        runtime = self._session_actors.get(session_id)
        if runtime is None:
            return
        runtime.remove_task(task_id)

    def get_active_task(self, operation_id: str) -> tuple[str, RuntimeTaskHandle] | None:
        runtime = self.get_session_actor_for_operation(operation_id)
        if runtime is None:
            return None
        handle = runtime.get_active_task(operation_id)
        if handle is None:
            return None
        return runtime.session_id, handle

    def list_active_tasks(self) -> list[tuple[str, RuntimeTaskHandle]]:
        active_tasks: list[tuple[str, RuntimeTaskHandle]] = []
        for runtime in self._session_actors.values():
            for handle in runtime.list_active_tasks():
                active_tasks.append((runtime.session_id, handle))
        return active_tasks

    # -- Holder management --

    def try_acquire_holder(self, session_id: str, holder_key: str) -> bool:
        runtime = self._ensure_session_actor(session_id)
        return runtime.try_acquire_holder(holder_key)

    def release_holder(self, session_id: str, holder_key: str) -> bool:
        runtime = self._session_actors.get(session_id)
        if runtime is None:
            return False
        return runtime.release_holder(holder_key)

    def force_release_holder(self, session_id: str) -> str | None:
        runtime = self._session_actors.get(session_id)
        if runtime is None:
            return None
        return runtime.force_release_holder()

    def is_held_by(self, session_id: str, holder_key: str) -> bool:
        runtime = self._session_actors.get(session_id)
        if runtime is None:
            return False
        return runtime.is_held_by(holder_key)

    def get_holder_key(self, session_id: str) -> str | None:
        runtime = self._session_actors.get(session_id)
        if runtime is None:
            return None
        return runtime.get_holder_key()

    def holder_is_active(self, session_id: str) -> bool:
        runtime = self._session_actors.get(session_id)
        if runtime is None:
            return False
        return runtime.holder_is_active()

    def cleanup_stale_holders(self) -> list[str]:
        """Force-release holders whose grace period has expired. Returns released session ids."""
        released: list[str] = []
        for session_id, runtime in self._session_actors.items():
            if not runtime.holder_is_active() and runtime.get_holder_key() is not None:
                runtime.force_release_holder()
                released.append(session_id)
        return released

    def _resolve_runtime_id(self, operation: op.Operation) -> str:
        session_id = getattr(operation, "session_id", None)
        if session_id is None:
            raise RuntimeError(f"Operation must be session-bound: {operation.type.value}")
        return session_id

    def _ensure_session_actor(self, runtime_id: str) -> SessionActor:
        runtime = self._session_actors.get(runtime_id)
        if runtime is not None:
            return runtime

        runtime = SessionActor(
            session_id=runtime_id,
            handle_operation=self._dispatch_operation,
            reject_operation=self._reject_operation_with_lifecycle,
            control_burst_quota=self._control_burst_quota,
        )
        self._session_actors[runtime_id] = runtime
        return runtime

    async def _dispatch_operation(self, operation: op.Operation) -> None:
        session_id = getattr(operation, "session_id", "?")
        hooks = self._operation_lifecycle_hooks
        if hooks is None:
            await self._handle_operation(operation)
            return

        try:
            await self._handle_operation(operation)
        except Exception as exc:
            log_debug(
                f"[{session_id}] failed [{operation.type.value}] op={operation.id[:8]} err={exc}",
                debug_type=DebugType.OPERATION,
            )
            self.mark_operation_completed(operation.id)
            await hooks.on_operation_finished(operation, "failed", str(exc))
            raise

        active = self.get_active_task(operation.id)
        if active is None:
            log_debug(
                f"[{session_id}] completed [{operation.type.value}] op={operation.id[:8]}",
                debug_type=DebugType.OPERATION,
            )
            self.mark_operation_completed(operation.id)
            await hooks.on_operation_finished(operation, "completed", None)
            return

        _session_id, handle = active
        self.bind_root_task(operation_id=operation.id, task_id=handle.task_id)

        async def _await_task_and_finish(captured_task: asyncio.Task[None]) -> None:
            try:
                await captured_task
            finally:
                log_debug(
                    f"[{session_id}] completed [{operation.type.value}] op={operation.id[:8]}",
                    debug_type=DebugType.OPERATION,
                )
                self.mark_operation_completed(operation.id)
                await hooks.on_operation_finished(operation, "completed", None)

        background_task = asyncio.create_task(_await_task_and_finish(handle.task))
        self._background_tasks.add(background_task)
        background_task.add_done_callback(self._background_tasks.discard)

    async def _reject_operation_with_lifecycle(self, operation: op.Operation, active_task_id: str | None) -> None:
        session_id = getattr(operation, "session_id", "?")
        log_debug(
            f"[{session_id}] rejected [{operation.type.value}] op={operation.id[:8]} active_task={active_task_id}",
            debug_type=DebugType.OPERATION,
        )
        hooks = self._operation_lifecycle_hooks
        if hooks is None:
            await self._reject_operation(operation, active_task_id)
            return

        try:
            await self._reject_operation(operation, active_task_id)
        finally:
            self.mark_operation_completed(operation.id)
            await hooks.on_operation_finished(operation, "rejected", None)

    async def _emit_operation_accepted(self, operation: op.Operation) -> None:
        session_id = getattr(operation, "session_id", "?")
        log_debug(
            f"[{session_id}] accepted [{operation.type.value}] op={operation.id[:8]}",
            debug_type=DebugType.OPERATION,
        )
        hooks = self._operation_lifecycle_hooks
        if hooks is None:
            return
        with contextlib.suppress(Exception):
            await hooks.on_operation_accepted(operation)


def _should_preempt_control(runtime: SessionActor, operation: op.Operation) -> bool:
    if not runtime.has_active_root_task():
        return False
    return isinstance(operation, op.InterruptOperation | op.UserInteractionRespondOperation)
