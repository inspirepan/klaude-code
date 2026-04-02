from __future__ import annotations

import asyncio
import contextlib
import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import Literal
from uuid import uuid4

from klaude_code.agent.agent import Agent
from klaude_code.agent.agent_profile import ModelProfileProvider
from klaude_code.agent.runtime_dispatcher import OperationDispatcher, OperationDispatcherPorts
from klaude_code.agent.runtime_llm import LLMClients
from klaude_code.control.event_bus import EventBus, event_publish_context
from klaude_code.control.session_registry import OperationLifecycleHooks, SessionRegistry
from klaude_code.control.user_interaction import PendingUserInteractionRequest
from klaude_code.log import DebugType, log_debug
from klaude_code.protocol import events, model, op, user_interaction
from klaude_code.session.session import Session


class OperationCompletionAwaiter:
    def __init__(self, event_bus: EventBus) -> None:
        self._subscription = event_bus.subscribe(None)
        self._futures: dict[str, asyncio.Future[None]] = {}
        self._completed_operation_ids: set[str] = set()
        self._consumer_task: asyncio.Task[None] = asyncio.create_task(self._consume())

    def register(self, operation_id: str) -> None:
        if operation_id in self._futures or operation_id in self._completed_operation_ids:
            raise RuntimeError(f"Operation already registered: {operation_id}")
        loop = asyncio.get_running_loop()
        self._futures[operation_id] = loop.create_future()

    def discard(self, operation_id: str) -> None:
        future = self._futures.pop(operation_id, None)
        if future is None:
            return
        if not future.done():
            future.cancel()

    async def wait_for(self, operation_id: str) -> None:
        if operation_id in self._completed_operation_ids:
            self._completed_operation_ids.discard(operation_id)
            return
        future = self._futures.get(operation_id)
        if future is None:
            return
        try:
            await future
        finally:
            self._futures.pop(operation_id, None)
            self._completed_operation_ids.discard(operation_id)

    async def stop(self) -> None:
        if not self._consumer_task.done():
            self._consumer_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._consumer_task
        for future in self._futures.values():
            if not future.done():
                future.set_result(None)
        self._futures.clear()
        self._completed_operation_ids.clear()

    async def _consume(self) -> None:
        async for envelope in self._subscription:
            event = envelope.event
            if isinstance(event, events.EndEvent):
                return
            if not isinstance(event, events.OperationFinishedEvent | events.OperationRejectedEvent):
                continue
            operation_id = event.operation_id
            future = self._futures.pop(operation_id, None)
            if future is None:
                self._completed_operation_ids.add(operation_id)
                continue
            if future.done():
                continue
            self._completed_operation_ids.add(operation_id)
            future.set_result(None)


class RuntimeFacade:
    """Runtime entry for CLI/TUI operation submission and lifecycle control."""

    def __init__(
        self,
        event_bus: EventBus,
        llm_clients: LLMClients,
        model_profile_provider: ModelProfileProvider | None = None,
        on_model_change: Callable[[str], None] | None = None,
        runtime_kind: Literal["tui", "web"] = "tui",
    ):
        self.runtime_id = uuid4().hex
        self.runtime_kind: Literal["tui", "web"] = runtime_kind
        self.pid = os.getpid()
        self.session_registry = SessionRegistry(
            handle_operation=self._execute_operation,
            reject_operation=self._reject_operation,
            operation_lifecycle_hooks=OperationLifecycleHooks(
                on_operation_accepted=self._emit_operation_accepted,
                on_operation_finished=self._emit_operation_finished,
            ),
        )
        self._operation_dispatcher = OperationDispatcher(
            event_bus,
            llm_clients,
            OperationDispatcherPorts(
                ensure_session_actor=self.session_registry.ensure_session_actor,
                get_session_actor=self.session_registry.get_session_actor,
                get_session_actor_for_operation=self.session_registry.get_session_actor_for_operation,
                list_session_actors=self.session_registry.list_session_actors,
                register_task=lambda session_id, operation_id, task_id, task: self.session_registry.register_task(
                    session_id=session_id,
                    operation_id=operation_id,
                    task_id=task_id,
                    task=task,
                ),
                remove_task=lambda session_id, task_id: self.session_registry.remove_task(
                    session_id=session_id,
                    task_id=task_id,
                ),
                close_session=self.close_session,
                request_user_interaction=self._request_user_interaction,
                respond_user_interaction=self._respond_user_interaction,
                cancel_pending_interactions=self._cancel_pending_user_interactions,
                on_child_task_state_change=self._on_child_task_state_change,
            ),
            model_profile_provider,
            on_model_change,
        )
        self._operation_awaiter = OperationCompletionAwaiter(event_bus)
        self._stopped = False

    def _session_owner(self) -> model.SessionOwner:
        return model.SessionOwner(runtime_id=self.runtime_id, runtime_kind=self.runtime_kind, pid=self.pid)

    @property
    def session_owner(self) -> model.SessionOwner:
        return self._session_owner()

    def _persist_session_owner(self, session_id: str, work_dir: Path | None = None) -> None:
        resolved_work_dir = work_dir
        if resolved_work_dir is None:
            runtime = self.session_registry.get_session_actor(session_id)
            if runtime is None:
                return
            agent = runtime.get_agent()
            if agent is None:
                return
            agent.session.runtime_owner = self._session_owner()
            agent.session.runtime_owner_heartbeat_at = time.time()
            resolved_work_dir = agent.session.work_dir
        Session.persist_runtime_owner(session_id, self._session_owner(), resolved_work_dir)

    def _clear_session_owner(self, session_id: str, work_dir: Path) -> None:
        Session.persist_runtime_owner(session_id, None, work_dir)

    async def heartbeat_session_owners(self) -> None:
        now = time.time()
        for runtime in self.session_registry.list_session_actors():
            agent = runtime.get_agent()
            if agent is None:
                continue
            agent.session.runtime_owner = self._session_owner()
            agent.session.runtime_owner_heartbeat_at = now
            await asyncio.to_thread(
                Session.persist_runtime_owner_heartbeat, runtime.session_id, now, agent.session.work_dir
            )

    async def _reject_operation(self, operation: op.Operation, active_task_id: str | None) -> None:
        session_id = getattr(operation, "session_id", None)
        if session_id is None:
            raise RuntimeError("Busy rejection requires session-bound operation")

        await self._operation_dispatcher.emit_event(
            events.OperationRejectedEvent(
                session_id=session_id,
                operation_id=operation.id,
                operation_type=operation.type.value,
                reason="session_busy",
                active_task_id=active_task_id,
            ),
            operation_id=operation.id,
        )
        await self._sync_session_state_from_snapshot(session_id)

    def _on_operation_applied(self, operation: op.Operation) -> None:
        self.session_registry.apply_operation_effect(operation)

    def _derive_session_state_from_snapshot(self, session_id: str) -> model.SessionRuntimeState:
        snapshot = self.session_registry.snapshot(session_id)
        if snapshot is None:
            return model.SessionRuntimeState.IDLE
        if snapshot.pending_request_count > 0:
            return model.SessionRuntimeState.WAITING_USER_INPUT
        if snapshot.active_root_task is not None or snapshot.child_task_count > 0:
            return model.SessionRuntimeState.RUNNING
        return model.SessionRuntimeState.IDLE

    async def _persist_session_state(self, session_id: str, session_state: model.SessionRuntimeState) -> None:
        try:
            runtime = self.session_registry.get_session_actor(session_id)
            if runtime is None:
                return
            agent = runtime.get_agent()
            if agent is None:
                return
            agent.session.session_state = session_state
            agent.session.runtime_owner = self._session_owner()
            agent.session.runtime_owner_heartbeat_at = time.time()
            work_dir = agent.session.work_dir
        except AttributeError:
            return
        await asyncio.to_thread(Session.persist_runtime_state, session_id, session_state, work_dir)
        await asyncio.to_thread(Session.persist_runtime_owner, session_id, self._session_owner(), work_dir)

    async def _sync_session_state_from_snapshot(self, session_id: str) -> None:
        session_state = self._derive_session_state_from_snapshot(session_id)
        if session_state == model.SessionRuntimeState.IDLE:
            runtime = self.session_registry.get_session_actor(session_id)
            agent = runtime.get_agent() if runtime is not None else None
            if agent is not None:
                await agent.session.wait_for_flush()
        await self._persist_session_state(session_id, session_state)

    def _respond_user_interaction(
        self,
        request_id: str,
        session_id: str,
        response: user_interaction.UserInteractionResponse,
    ) -> None:
        self.session_registry.respond_user_interaction(
            request_id=request_id,
            session_id=session_id,
            response=response,
        )

    async def _request_user_interaction(
        self,
        request: PendingUserInteractionRequest,
    ) -> user_interaction.UserInteractionResponse:
        runtime = self.session_registry.ensure_session_actor(request.session_id)
        future = runtime.open_pending_interaction(request)
        await self._persist_session_state(request.session_id, model.SessionRuntimeState.WAITING_USER_INPUT)
        try:
            return await future
        finally:
            await self._sync_session_state_from_snapshot(request.session_id)

    def _cancel_pending_user_interactions(
        self,
        session_id: str | None,
    ) -> list[PendingUserInteractionRequest]:
        return self.session_registry.cancel_pending_interactions_with_requests(session_id=session_id)

    def _on_child_task_state_change(self, session_id: str, task_id: str, is_active: bool) -> None:
        self.session_registry.mark_child_task_state(session_id=session_id, task_id=task_id, is_active=is_active)

    async def _emit_operation_accepted(self, operation: op.Operation) -> None:
        session_id = getattr(operation, "session_id", None)
        if session_id is None:
            raise RuntimeError("OperationAcceptedEvent requires session-bound operation")
        await self._operation_dispatcher.emit_event(
            events.OperationAcceptedEvent(
                session_id=session_id,
                operation_id=operation.id,
                operation_type=operation.type.value,
            ),
            operation_id=operation.id,
        )
        if _should_mark_running_on_accept(operation):
            await self._persist_session_state(session_id, model.SessionRuntimeState.RUNNING)

    async def _emit_operation_finished(
        self,
        operation: op.Operation,
        status: Literal["completed", "rejected", "failed"],
        error_message: str | None = None,
    ) -> None:
        session_id = getattr(operation, "session_id", None)
        if session_id is None:
            return
        if isinstance(operation, op.InitAgentOperation):
            runtime = self.session_registry.get_session_actor(session_id)
            agent = runtime.get_agent() if runtime is not None else None
            if agent is not None:
                agent.session.session_state = model.SessionRuntimeState.IDLE
                agent.session.runtime_owner = self._session_owner()
                agent.session.runtime_owner_heartbeat_at = time.time()
                await asyncio.to_thread(agent.session.ensure_meta_exists)
            await asyncio.to_thread(self._persist_session_owner, session_id, operation.work_dir)
        await self._operation_dispatcher.emit_event(
            events.OperationFinishedEvent(
                session_id=session_id,
                operation_id=operation.id,
                operation_type=operation.type.value,
                status=status,
                error_message=error_message,
            ),
            operation_id=operation.id,
        )
        if isinstance(operation, op.InitAgentOperation):
            return
        await self._sync_session_state_from_snapshot(session_id)

    async def submit(self, operation: op.Operation) -> str:
        if self._stopped:
            raise RuntimeError("RuntimeFacade is stopped")

        self._operation_awaiter.register(operation.id)
        try:
            await self.session_registry.submit(operation)
        except Exception:
            self._operation_awaiter.discard(operation.id)
            raise

        log_debug(
            f"Submitted operation {operation.type} with ID {operation.id}",
            debug_type=DebugType.EXECUTION,
        )

        return operation.id

    async def emit_event(self, event: events.Event) -> None:
        await self._operation_dispatcher.emit_event(event)

    def current_session_id(self) -> str | None:
        return self._operation_dispatcher.current_session_id()

    @property
    def current_agent(self) -> Agent | None:
        return self._operation_dispatcher.current_agent

    def has_running_tasks(self) -> bool:
        return any(not active.task.done() for active in self._operation_dispatcher.list_active_tasks())

    async def close_session(self, session_id: str, force: bool = False) -> bool:
        cancelled_requests: list[PendingUserInteractionRequest] = []
        work_dir: Path | None = None
        get_actor = getattr(self.session_registry, "get_session_actor", None)
        if callable(get_actor):
            runtime = self.session_registry.get_session_actor(session_id)
            if runtime is not None:
                agent = runtime.get_agent()
                if agent is not None:
                    work_dir = agent.session.work_dir
        if force:
            cancelled_requests = self.session_registry.cancel_pending_interactions_with_requests(session_id=session_id)

        closed = await self.session_registry.close_session(session_id, force=force)
        if closed:
            await self._persist_session_state(session_id, model.SessionRuntimeState.IDLE)
            if work_dir is not None:
                await asyncio.to_thread(self._clear_session_owner, session_id, work_dir)
            for request in cancelled_requests:
                await self._operation_dispatcher.emit_event(
                    events.UserInteractionCancelledEvent(
                        session_id=request.session_id,
                        request_id=request.request_id,
                        reason="session_close",
                    ),
                    causation_id=request.request_id,
                )
                await self._operation_dispatcher.emit_event(
                    events.UserInteractionResolvedEvent(
                        session_id=request.session_id,
                        request_id=request.request_id,
                        status="cancelled",
                    ),
                    causation_id=request.request_id,
                )
        return closed

    async def reclaim_idle_sessions(self, *, idle_for_seconds: float) -> list[str]:
        # Never reclaim the primary (TUI-active) session.
        primary = self._operation_dispatcher.current_session_id()
        exclude = {primary} if primary is not None else None
        return await self.session_registry.reclaim_idle_sessions(idle_for_seconds=idle_for_seconds, exclude=exclude)

    async def wait_for(self, operation_id: str) -> None:
        await self._operation_awaiter.wait_for(operation_id)

    async def submit_and_wait(self, operation: op.Operation) -> None:
        operation_id = await self.submit(operation)
        await self.wait_for(operation_id)

    # -- Holder management --

    async def try_acquire_holder(self, session_id: str, holder_key: str) -> bool:
        acquired = self.session_registry.try_acquire_holder(session_id, holder_key)
        if acquired:
            await self._operation_dispatcher.emit_event(events.SessionHolderAcquiredEvent(session_id=session_id))
        else:
            await self._operation_dispatcher.emit_event(events.SessionHolderDeniedEvent(session_id=session_id))
        return acquired

    async def release_holder(self, session_id: str, holder_key: str) -> bool:
        released = self.session_registry.release_holder(session_id, holder_key)
        if released:
            await self._operation_dispatcher.emit_event(events.SessionHolderReleasedEvent(session_id=session_id))
        return released

    def is_held_by(self, session_id: str, holder_key: str) -> bool:
        return self.session_registry.is_held_by(session_id, holder_key)

    def get_holder_key(self, session_id: str) -> str | None:
        return self.session_registry.get_holder_key(session_id)

    def holder_is_active(self, session_id: str) -> bool:
        return self.session_registry.holder_is_active(session_id)

    async def stop(self) -> None:
        self._stopped = True
        sessions_to_idle: list[tuple[str, Agent]] = []
        for runtime in self.session_registry.list_session_actors():
            agent = runtime.get_agent()
            if agent is None:
                continue
            sessions_to_idle.append((runtime.session_id, agent))

        cancelled_requests = self._operation_dispatcher.cancel_pending_user_interactions(session_id=None)
        for request in cancelled_requests:
            await self._operation_dispatcher.emit_event(
                events.UserInteractionCancelledEvent(
                    session_id=request.session_id,
                    request_id=request.request_id,
                    reason="shutdown",
                ),
                causation_id=request.request_id,
            )
            await self._operation_dispatcher.emit_event(
                events.UserInteractionResolvedEvent(
                    session_id=request.session_id,
                    request_id=request.request_id,
                    status="cancelled",
                ),
                causation_id=request.request_id,
            )

        tasks_to_await: list[asyncio.Task[None]] = []
        for active in self._operation_dispatcher.list_active_tasks():
            task = active.task
            if not task.done():
                task.cancel()
                tasks_to_await.append(task)

        if tasks_to_await:
            await asyncio.gather(*tasks_to_await, return_exceptions=True)

        for _session_id, agent in sessions_to_idle:
            with contextlib.suppress(Exception):
                await agent.session.wait_for_flush()

        for session_id, agent in sessions_to_idle:
            agent.session.session_state = model.SessionRuntimeState.IDLE
            agent.session.runtime_owner = None
            with contextlib.suppress(Exception):
                await asyncio.to_thread(
                    Session.persist_runtime_state,
                    session_id,
                    model.SessionRuntimeState.IDLE,
                    agent.session.work_dir,
                )
            with contextlib.suppress(Exception):
                await asyncio.to_thread(Session.persist_runtime_owner, session_id, None, agent.session.work_dir)

        await self.session_registry.stop()
        await self._operation_awaiter.stop()
        self._operation_dispatcher.clear_active_tasks()

        log_debug("RuntimeFacade stopped", debug_type=DebugType.EXECUTION)

    async def _execute_operation(self, operation: op.Operation) -> None:
        try:
            log_debug(
                f"Handling operation {operation.id} of type {operation.type.value}",
                debug_type=DebugType.EXECUTION,
            )

            with event_publish_context(operation_id=operation.id):
                await operation.execute(handler=self._operation_dispatcher)
            self._on_operation_applied(operation)
        except Exception as e:
            log_debug(
                f"Failed to handle operation {operation.id}: {e!s}",
                debug_type=DebugType.EXECUTION,
            )
            session_id = getattr(operation, "session_id", None)
            await self._operation_dispatcher.emit_event(
                events.ErrorEvent(
                    error_message=f"Operation failed: {e!s}",
                    can_retry=False,
                    session_id=session_id or "__app__",
                ),
                operation_id=operation.id,
            )
            raise


def _should_mark_running_on_accept(operation: op.Operation) -> bool:
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
