from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from klaude_code.core.user_interaction import PendingUserInteractionRequest
from klaude_code.protocol import llm_param, op


@dataclass(frozen=True)
class _StopSignal:
    pass


_STOP_SIGNAL = _StopSignal()


def _empty_sub_agent_models() -> dict[str, str | None]:
    return {}


@dataclass(frozen=True)
class RootTaskState:
    operation_id: str
    task_id: str
    kind: str


@dataclass
class SessionRuntimeConfig:
    model_name: str | None = None
    thinking: llm_param.Thinking | None = None
    compact_model: str | None = None
    sub_agent_models: dict[str, str | None] = field(default_factory=_empty_sub_agent_models)


@dataclass(frozen=True)
class SessionRuntimeSnapshot:
    session_id: str
    active_root_task: RootTaskState | None
    pending_request_count: int
    is_idle: bool
    config: SessionRuntimeConfig


class SessionRuntime:
    def __init__(
        self,
        *,
        session_id: str,
        handle_operation: Callable[[op.Operation], Awaitable[None]],
        reject_operation: Callable[[op.Operation, str | None], Awaitable[None]],
        control_burst_quota: int = 8,
    ) -> None:
        self.session_id = session_id
        self.control_mailbox: asyncio.Queue[op.Operation | _StopSignal] = asyncio.Queue()
        self.normal_mailbox: asyncio.Queue[op.Operation] = asyncio.Queue()
        self._handle_operation = handle_operation
        self._reject_operation = reject_operation
        self._active_root_task: RootTaskState | None = None
        self._pending_requests: dict[str, PendingUserInteractionRequest] = {}
        self._config = SessionRuntimeConfig()
        self._idle_since_monotonic: float | None = time.monotonic()
        self._control_burst_quota = control_burst_quota
        self._control_burst_count = 0
        self._worker_task: asyncio.Task[None] = asyncio.create_task(self._run_loop())

    async def enqueue(self, operation: op.Operation) -> None:
        self._mark_active()
        if _is_control_operation(operation):
            await self.control_mailbox.put(operation)
            return
        await self.normal_mailbox.put(operation)

    async def stop(self) -> None:
        while True:
            try:
                _ = self.control_mailbox.get_nowait()
                self.control_mailbox.task_done()
            except asyncio.QueueEmpty:
                break
        while True:
            try:
                _ = self.normal_mailbox.get_nowait()
                self.normal_mailbox.task_done()
            except asyncio.QueueEmpty:
                break
        await self.control_mailbox.put(_STOP_SIGNAL)
        await self._worker_task

    def mark_operation_completed(self, operation_id: str) -> None:
        active = self._active_root_task
        if active is None:
            self._refresh_idle_since()
            return
        if active.operation_id == operation_id:
            self._active_root_task = None
        self._refresh_idle_since()

    def bind_root_task(self, *, operation_id: str, task_id: str) -> None:
        active = self._active_root_task
        if active is None:
            return
        if active.operation_id != operation_id:
            return
        self._active_root_task = RootTaskState(operation_id=active.operation_id, task_id=task_id, kind=active.kind)

    def mark_request_pending(self, request: PendingUserInteractionRequest) -> None:
        self._pending_requests[request.request_id] = request
        self._mark_active()

    def mark_request_resolved(self, request_id: str) -> None:
        self._pending_requests.pop(request_id, None)
        self._refresh_idle_since()

    def has_pending_request(self, request_id: str) -> bool:
        return request_id in self._pending_requests

    def pending_request_count(self) -> int:
        return len(self._pending_requests)

    def apply_operation_effect(self, operation: op.Operation) -> None:
        if isinstance(operation, op.ChangeModelOperation):
            self._config.model_name = operation.model_name
            self._config.thinking = None
            return
        if isinstance(operation, op.ChangeThinkingOperation):
            self._config.thinking = operation.thinking
            return
        if isinstance(operation, op.ChangeCompactModelOperation):
            self._config.compact_model = operation.model_name
            return
        if isinstance(operation, op.ChangeSubAgentModelOperation):
            self._config.sub_agent_models[operation.sub_agent_type] = operation.model_name

    def config_snapshot(self) -> SessionRuntimeConfig:
        return SessionRuntimeConfig(
            model_name=self._config.model_name,
            thinking=self._config.thinking.model_copy(deep=True) if self._config.thinking is not None else None,
            compact_model=self._config.compact_model,
            sub_agent_models=dict(self._config.sub_agent_models),
        )

    def snapshot(self) -> SessionRuntimeSnapshot:
        active = self._active_root_task
        active_snapshot = (
            RootTaskState(operation_id=active.operation_id, task_id=active.task_id, kind=active.kind)
            if active is not None
            else None
        )
        return SessionRuntimeSnapshot(
            session_id=self.session_id,
            active_root_task=active_snapshot,
            pending_request_count=len(self._pending_requests),
            is_idle=self.is_idle(),
            config=self.config_snapshot(),
        )

    def has_active_root_task(self) -> bool:
        return self._active_root_task is not None

    def is_idle(self) -> bool:
        return (
            self._active_root_task is None
            and not self._pending_requests
            and self.control_mailbox.empty()
            and self.normal_mailbox.empty()
        )

    def idle_for_seconds(self, now: float | None = None) -> float | None:
        if not self.is_idle():
            self._idle_since_monotonic = None
            return None

        current = now if now is not None else time.monotonic()
        if self._idle_since_monotonic is None:
            self._idle_since_monotonic = current
            return 0.0
        return current - self._idle_since_monotonic

    def _mark_active(self) -> None:
        self._idle_since_monotonic = None

    def _refresh_idle_since(self) -> None:
        if self.is_idle() and self._idle_since_monotonic is None:
            self._idle_since_monotonic = time.monotonic()

    async def _run_loop(self) -> None:
        while True:
            item = await self._next_item()
            try:
                if isinstance(item, _StopSignal):
                    return
                if _is_root_operation(item) and self._active_root_task is not None:
                    await self._reject_operation(item, self._active_root_task.task_id)
                    continue
                if _is_root_operation(item):
                    self._active_root_task = RootTaskState(
                        operation_id=item.id,
                        task_id=item.id,
                        kind=_root_task_kind(item),
                    )
                await self._handle_operation(item)
            finally:
                if isinstance(item, _StopSignal) or _is_control_operation(item):
                    self.control_mailbox.task_done()
                else:
                    self.normal_mailbox.task_done()

    async def _next_item(self) -> op.Operation | _StopSignal:
        if self._control_burst_count >= self._control_burst_quota and not self.normal_mailbox.empty():
            self._control_burst_count = 0
            return self.normal_mailbox.get_nowait()

        if not self.control_mailbox.empty():
            item = self.control_mailbox.get_nowait()
            if isinstance(item, _StopSignal):
                return item
            self._control_burst_count += 1
            return item

        if not self.normal_mailbox.empty():
            self._control_burst_count = 0
            return self.normal_mailbox.get_nowait()

        control_task = asyncio.create_task(self.control_mailbox.get())
        normal_task = asyncio.create_task(self.normal_mailbox.get())
        done, pending = await asyncio.wait({control_task, normal_task}, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        for task in pending:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        selected_task = next(iter(done))
        selected = selected_task.result()
        if isinstance(selected, _StopSignal):
            return selected
        if selected_task is control_task:
            self._control_burst_count += 1
        else:
            self._control_burst_count = 0
        return selected


def _is_root_operation(operation: op.Operation) -> bool:
    return isinstance(
        operation,
        op.RunAgentOperation | op.RunBashOperation | op.ContinueAgentOperation | op.CompactSessionOperation,
    )


def _is_control_operation(operation: op.Operation) -> bool:
    return isinstance(operation, op.InterruptOperation | op.UserInteractionRespondOperation | op.CloseSessionOperation)


def _root_task_kind(operation: op.Operation) -> str:
    if isinstance(operation, op.RunAgentOperation | op.ContinueAgentOperation):
        return "agent"
    if isinstance(operation, op.RunBashOperation):
        return "bash"
    if isinstance(operation, op.CompactSessionOperation):
        return "compact"
    raise RuntimeError(f"unsupported root operation kind: {operation.type.value}")


