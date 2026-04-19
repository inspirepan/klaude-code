from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from klaude_code.control.user_interaction import PendingUserInteractionRequest
from klaude_code.protocol import llm_param, op, user_interaction

if TYPE_CHECKING:
    from klaude_code.agent.agent import Agent
    from klaude_code.agent.runtime_llm import LLMClients

@dataclass(frozen=True)
class _StopSignal:
    pass

_STOP_SIGNAL = _StopSignal()

def _empty_sub_agent_models() -> dict[str, str | None]:
    return {}

def _empty_child_task_ids() -> set[str]:
    return set()

def _empty_pending_requests() -> dict[str, _PendingInteractionState]:
    return {}

def _empty_task_handles() -> dict[str, RuntimeTaskHandle]:
    return {}

def _empty_operation_task_ids() -> dict[str, str]:
    return {}

@dataclass(frozen=True)
class RootTaskState:
    operation_id: str
    task_id: str
    kind: str

@dataclass
class _PendingInteractionState:
    request: PendingUserInteractionRequest
    future: asyncio.Future[user_interaction.UserInteractionResponse]

@dataclass
class RuntimeTaskHandle:
    task_id: str
    operation_id: str
    task: asyncio.Task[None]

HOLDER_GRACE_SECONDS = 10.0

@dataclass
class SessionHolder:
    """Tracks which frontend connection exclusively holds a session."""

    holder_key: str
    acquired_at: float  # monotonic
    released_at: float | None = None  # monotonic; set on disconnect, cleared on reacquire

@dataclass
class SessionConfig:
    model_name: str | None = None
    thinking: llm_param.Thinking | None = None
    compact_model: str | None = None
    sub_agent_models: dict[str, str | None] = field(default_factory=_empty_sub_agent_models)

@dataclass
class SessionState:
    active_root_task: RootTaskState | None = None
    child_task_ids: set[str] = field(default_factory=_empty_child_task_ids)
    pending_requests: dict[str, _PendingInteractionState] = field(default_factory=_empty_pending_requests)
    task_handles: dict[str, RuntimeTaskHandle] = field(default_factory=_empty_task_handles)
    operation_task_ids: dict[str, str] = field(default_factory=_empty_operation_task_ids)
    agent: Agent | None = None
    llm_clients: LLMClients | None = None
    config: SessionConfig = field(default_factory=SessionConfig)
    holder: SessionHolder | None = None
    idle_since_monotonic: float | None = None
    control_burst_count: int = 0

@dataclass(frozen=True)
class SessionActorSnapshot:
    session_id: str
    active_root_task: RootTaskState | None
    child_task_count: int
    pending_request_count: int
    is_idle: bool
    config: SessionConfig
    holder_key: str | None = None

class SessionActor:
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
        self._state = SessionState(idle_since_monotonic=time.monotonic())
        self._control_burst_quota = control_burst_quota
        self._worker_task: asyncio.Task[None] = asyncio.create_task(self._run_loop())

    async def enqueue(self, operation: op.Operation) -> None:
        self._mark_active()
        if _is_control_operation(operation):
            await self.control_mailbox.put(operation)
            return
        await self.normal_mailbox.put(operation)

    async def run_control_preemptive(self, operation: op.Operation) -> None:
        if not _is_control_operation(operation):
            raise RuntimeError("preemptive execution only supports control operations")
        self._mark_active()
        await self._handle_operation(operation)

    async def stop(self) -> None:
        self.cancel_pending_interactions()
        tasks_to_await: list[asyncio.Task[None]] = []
        for _, task in self.cancel_active_tasks():
            if not task.done():
                task.cancel()
                tasks_to_await.append(task)
        if tasks_to_await:
            await asyncio.gather(*tasks_to_await, return_exceptions=True)

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
        self.clear_execution_state()

    def set_agent(self, agent: Agent) -> None:
        self._state.agent = agent
        self._mark_active()

    def get_agent(self) -> Agent | None:
        return self._state.agent

    def set_llm_clients(self, llm_clients: LLMClients) -> None:
        self._state.llm_clients = llm_clients
        self._mark_active()

    def get_llm_clients(self) -> LLMClients | None:
        return self._state.llm_clients

    def clear_execution_state(self) -> None:
        self._state.agent = None
        self._state.llm_clients = None
        self._state.task_handles.clear()
        self._state.operation_task_ids.clear()
        self._refresh_idle_since()

    def register_task(self, *, operation_id: str, task_id: str, task: asyncio.Task[None]) -> None:
        self._state.task_handles[task_id] = RuntimeTaskHandle(task_id=task_id, operation_id=operation_id, task=task)
        self._state.operation_task_ids[operation_id] = task_id
        self._mark_active()

    def get_active_task(self, operation_id: str) -> RuntimeTaskHandle | None:
        task_id = self._state.operation_task_ids.get(operation_id)
        if task_id is None:
            return None
        return self._state.task_handles.get(task_id)

    def list_active_tasks(self) -> list[RuntimeTaskHandle]:
        return list(self._state.task_handles.values())

    def remove_task(self, task_id: str) -> None:
        handle = self._state.task_handles.pop(task_id, None)
        if handle is not None:
            current_task_id = self._state.operation_task_ids.get(handle.operation_id)
            if current_task_id == task_id:
                self._state.operation_task_ids.pop(handle.operation_id, None)
        active = self._state.active_root_task
        if active is not None and active.task_id == task_id:
            self._state.active_root_task = None
        self._refresh_idle_since()

    def cancel_active_tasks(self) -> list[tuple[str, asyncio.Task[None]]]:
        tasks_to_cancel: list[tuple[str, asyncio.Task[None]]] = []
        for task_id, handle in list(self._state.task_handles.items()):
            if handle.task.done():
                self.remove_task(task_id)
                continue
            tasks_to_cancel.append((task_id, handle.task))
        return tasks_to_cancel

    def open_pending_interaction(
        self,
        request: PendingUserInteractionRequest,
    ) -> asyncio.Future[user_interaction.UserInteractionResponse]:
        request_id = request.request_id
        if request_id in self._state.pending_requests:
            raise RuntimeError(f"Duplicate user interaction request id: {request_id}")

        loop = asyncio.get_running_loop()
        future: asyncio.Future[user_interaction.UserInteractionResponse] = loop.create_future()
        self._state.pending_requests[request_id] = _PendingInteractionState(request=request, future=future)

        def _on_done(_future: asyncio.Future[user_interaction.UserInteractionResponse]) -> None:
            self._finalize_pending_request(request_id)

        future.add_done_callback(_on_done)
        self._mark_active()
        return future

    def resolve_pending_interaction(
        self,
        *,
        request_id: str,
        session_id: str,
        response: user_interaction.UserInteractionResponse,
    ) -> None:
        pending = self._state.pending_requests.get(request_id)
        if pending is None:
            raise ValueError("No pending user interaction")
        if pending.request.session_id != session_id:
            raise ValueError("Session mismatch for pending user interaction")
        if response.status == "submitted" and response.payload is None:
            raise ValueError("Submitted response must include payload")

        if not pending.future.done():
            pending.future.set_result(response)
        # Eagerly finalize so the snapshot is immediately up-to-date.
        # The future's done callback (_on_done) is idempotent and will no-op.
        self._finalize_pending_request(request_id)

    def cancel_pending_interactions(self) -> list[PendingUserInteractionRequest]:
        cancelled: list[PendingUserInteractionRequest] = []
        for request_id, pending in list(self._state.pending_requests.items()):
            cancelled.append(pending.request)
            if not pending.future.done():
                pending.future.cancel()
            self._finalize_pending_request(request_id)
        return cancelled

    # -- Holder management --

    def try_acquire_holder(self, key: str, *, now: float | None = None) -> bool:
        """Try to acquire exclusive hold. Returns True on success."""
        current = now if now is not None else time.monotonic()
        holder = self._state.holder
        if holder is None:
            self._state.holder = SessionHolder(holder_key=key, acquired_at=current)
            return True
        # Active (not released) holder -- same key is idempotent, different key denied.
        if holder.released_at is None:
            return holder.holder_key == key
        # Released holder -- within grace period only the same key can reacquire.
        grace_expired = (current - holder.released_at) >= HOLDER_GRACE_SECONDS
        if not grace_expired and holder.holder_key == key:
            holder.released_at = None
            return True
        # Grace expired -- anyone can take over.
        if grace_expired:
            self._state.holder = SessionHolder(holder_key=key, acquired_at=current)
            return True
        return False

    def release_holder(self, key: str, *, now: float | None = None) -> bool:
        """Mark holder as released (starts grace period). Returns True if key matched."""
        holder = self._state.holder
        if holder is None or holder.holder_key != key:
            return False
        holder.released_at = now if now is not None else time.monotonic()
        return True

    def force_release_holder(self) -> str | None:
        """Unconditionally clear the holder. Returns the old holder key."""
        holder = self._state.holder
        if holder is None:
            return None
        old_key = holder.holder_key
        self._state.holder = None
        return old_key

    def is_held_by(self, key: str) -> bool:
        holder = self._state.holder
        if holder is None:
            return False
        return holder.holder_key == key and holder.released_at is None

    def get_holder_key(self) -> str | None:
        holder = self._state.holder
        if holder is None:
            return None
        return holder.holder_key

    def holder_is_active(self, *, now: float | None = None) -> bool:
        """True if a holder exists and has not exceeded the grace period."""
        holder = self._state.holder
        if holder is None:
            return False
        if holder.released_at is None:
            return True
        current = now if now is not None else time.monotonic()
        return (current - holder.released_at) < HOLDER_GRACE_SECONDS

    # -- Operation lifecycle --

    def mark_operation_completed(self, operation_id: str) -> None:
        active = self._state.active_root_task
        if active is not None and active.operation_id == operation_id:
            self._state.active_root_task = None
        self._refresh_idle_since()

    def bind_root_task(self, *, operation_id: str, task_id: str) -> None:
        active = self._state.active_root_task
        if active is None or active.operation_id != operation_id:
            return
        self._state.active_root_task = RootTaskState(
            operation_id=active.operation_id, task_id=task_id, kind=active.kind
        )

    def mark_child_task_started(self, task_id: str) -> None:
        self._state.child_task_ids.add(task_id)
        self._mark_active()

    def mark_child_task_completed(self, task_id: str) -> None:
        self._state.child_task_ids.discard(task_id)
        self._refresh_idle_since()

    def pending_request_count(self) -> int:
        return len(self._state.pending_requests)

    def pending_requests_snapshot(self) -> list[PendingUserInteractionRequest]:
        return [pending.request for pending in self._state.pending_requests.values()]

    def apply_operation_effect(self, operation: op.Operation) -> None:
        if isinstance(operation, op.ChangeModelOperation):
            self._state.config.model_name = operation.model_name
            self._state.config.thinking = None
            return
        if isinstance(operation, op.ChangeThinkingOperation):
            self._state.config.thinking = operation.thinking
            return
        if isinstance(operation, op.ChangeCompactModelOperation):
            self._state.config.compact_model = operation.model_name
            return
        if isinstance(operation, op.ChangeSubAgentModelOperation):
            self._state.config.sub_agent_models[operation.sub_agent_type] = operation.model_name

    def config_snapshot(self) -> SessionConfig:
        return SessionConfig(
            model_name=self._state.config.model_name,
            thinking=self._state.config.thinking.model_copy(deep=True)
            if self._state.config.thinking is not None
            else None,
            compact_model=self._state.config.compact_model,
            sub_agent_models=dict(self._state.config.sub_agent_models),
        )

    def snapshot(self) -> SessionActorSnapshot:
        return SessionActorSnapshot(
            session_id=self.session_id,
            active_root_task=self._state.active_root_task,
            child_task_count=len(self._state.child_task_ids),
            pending_request_count=len(self._state.pending_requests),
            is_idle=self.is_idle(),
            config=self.config_snapshot(),
            holder_key=self.get_holder_key(),
        )

    def has_active_root_task(self) -> bool:
        return self._state.active_root_task is not None

    def is_idle(self) -> bool:
        return (
            self._state.active_root_task is None
            and not self._state.child_task_ids
            and not self._state.pending_requests
            and not self._state.task_handles
            and self.control_mailbox.empty()
            and self.normal_mailbox.empty()
        )

    def idle_for_seconds(self, now: float | None = None) -> float | None:
        if not self.is_idle():
            self._state.idle_since_monotonic = None
            return None

        current = now if now is not None else time.monotonic()
        if self._state.idle_since_monotonic is None:
            self._state.idle_since_monotonic = current
            return 0.0
        return current - self._state.idle_since_monotonic

    def _mark_active(self) -> None:
        self._state.idle_since_monotonic = None

    def _refresh_idle_since(self) -> None:
        if self.is_idle() and self._state.idle_since_monotonic is None:
            self._state.idle_since_monotonic = time.monotonic()

    def _finalize_pending_request(self, request_id: str) -> None:
        pending = self._state.pending_requests.pop(request_id, None)
        if pending is None:
            return
        self._refresh_idle_since()

    async def _run_loop(self) -> None:
        while True:
            item = await self._next_item()
            try:
                if isinstance(item, _StopSignal):
                    return
                active_root_task = self._state.active_root_task
                if _is_root_operation(item) and active_root_task is not None:
                    await self._reject_operation(item, active_root_task.task_id)
                    continue
                if _is_root_operation(item):
                    self._state.active_root_task = RootTaskState(
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
        if self._state.control_burst_count >= self._control_burst_quota and not self.normal_mailbox.empty():
            self._state.control_burst_count = 0
            return self.normal_mailbox.get_nowait()

        if not self.control_mailbox.empty():
            item = self.control_mailbox.get_nowait()
            if isinstance(item, _StopSignal):
                return item
            self._state.control_burst_count += 1
            return item

        if not self.normal_mailbox.empty():
            self._state.control_burst_count = 0
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
            self._state.control_burst_count += 1
        else:
            self._state.control_burst_count = 0
        return selected

def _is_root_operation(operation: op.Operation) -> bool:
    return isinstance(
        operation,
        op.RunAgentOperation
        | op.RunBashOperation
        | op.ContinueAgentOperation
        | op.CompactSessionOperation
        | op.RequestModelOperation
        | op.RequestThinkingOperation
        | op.RequestSubAgentModelOperation,
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
    if isinstance(
        operation,
        op.RequestModelOperation | op.RequestThinkingOperation | op.RequestSubAgentModelOperation,
    ):
        return "config_request"
    raise RuntimeError(f"unsupported root operation kind: {operation.type.value}")
