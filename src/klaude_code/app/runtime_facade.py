from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable
from pathlib import Path
from typing import Literal

from klaude_code.agent.agent import Agent
from klaude_code.agent.agent_profile import ModelProfileProvider
from klaude_code.agent.runtime.dispatcher import OperationDispatcher, OperationDispatcherPorts
from klaude_code.agent.runtime.llm import LLMClients
from klaude_code.app.session_lease import SessionLease
from klaude_code.control.event_bus import EventBus, event_publish_context
from klaude_code.control.runtime.registry import OperationLifecycleHooks, SessionRegistry
from klaude_code.control.user_interaction import PendingUserInteractionRequest
from klaude_code.log import DebugType, log_debug
from klaude_code.protocol import events, op, user_interaction
from klaude_code.protocol.shell_task import ShellTaskSnapshot
from klaude_code.tool.shell.task_manager import ShellTaskManager


class OperationCompletionAwaiter:
    def __init__(self, event_bus: EventBus) -> None:
        self._subscription = event_bus.subscribe(None)
        self._futures: dict[
            str,
            asyncio.Future[Literal["completed", "rejected", "failed"] | None],
        ] = {}
        self._completed_operations: dict[str, Literal["completed", "rejected", "failed"]] = {}
        self._consumer_task: asyncio.Task[None] = asyncio.create_task(self._consume())

    def register(self, operation_id: str) -> None:
        if operation_id in self._futures or operation_id in self._completed_operations:
            raise RuntimeError(f"Operation already registered: {operation_id}")
        loop = asyncio.get_running_loop()
        self._futures[operation_id] = loop.create_future()

    def discard(self, operation_id: str) -> None:
        future = self._futures.pop(operation_id, None)
        if future is None:
            return
        if not future.done():
            future.cancel()

    async def wait_for(self, operation_id: str) -> Literal["completed", "rejected", "failed"] | None:
        if operation_id in self._completed_operations:
            return self._completed_operations.pop(operation_id)
        future = self._futures.get(operation_id)
        if future is None:
            return None
        try:
            return await future
        finally:
            self._futures.pop(operation_id, None)
            self._completed_operations.pop(operation_id, None)

    async def stop(self) -> None:
        if not self._consumer_task.done():
            self._consumer_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._consumer_task
        for future in self._futures.values():
            if not future.done():
                future.set_result(None)
        self._futures.clear()
        self._completed_operations.clear()

    async def _consume(self) -> None:
        async for envelope in self._subscription:
            event = envelope.event
            if isinstance(event, events.EndEvent):
                return
            if not isinstance(event, events.OperationFinishedEvent | events.OperationRejectedEvent):
                continue
            operation_id = event.operation_id
            status = event.status if isinstance(event, events.OperationFinishedEvent) else "rejected"
            future = self._futures.pop(operation_id, None)
            if future is None:
                self._completed_operations[operation_id] = status
                continue
            if future.done():
                continue
            self._completed_operations[operation_id] = status
            future.set_result(status)


class RuntimeFacade:
    """Runtime entry for CLI/TUI operation submission and lifecycle control."""

    def __init__(
        self,
        event_bus: EventBus,
        llm_clients: LLMClients,
        model_profile_provider: ModelProfileProvider | None = None,
        on_model_change: Callable[[str], None] | None = None,
    ):
        self._stopped = False
        self._session_leases: dict[str, SessionLease] = {}
        self.shell_task_manager = ShellTaskManager(
            on_update=self._shell_tasks_updated, on_complete=self._shell_completed
        )
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
                submit_operation=self.submit,
                wait_for_operation=self.wait_for,
            ),
            model_profile_provider,
            on_model_change,
            shell_task_manager=self.shell_task_manager,
        )
        self._operation_awaiter = OperationCompletionAwaiter(event_bus)
        self.task_manager = self._operation_dispatcher.task_manager
        self.peer_control = self._operation_dispatcher.peer_control
        self._stopped = False

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

    def _on_operation_applied(self, operation: op.Operation) -> None:
        self.session_registry.apply_operation_effect(operation)

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
        return await future

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
                await asyncio.to_thread(agent.session.ensure_meta_exists)
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

    async def submit(self, operation: op.Operation) -> str:
        if self._stopped:
            raise RuntimeError("RuntimeFacade is stopped")
        if isinstance(operation, op.InitAgentOperation):
            self.claim_session(operation.session_id)

        self._operation_awaiter.register(operation.id)
        try:
            await self.session_registry.submit(operation)
        except Exception:
            self.session_registry.mark_operation_completed(operation.id)
            self._operation_awaiter.discard(operation.id)
            raise

        log_debug(
            f"Submitted operation {operation.type} with ID {operation.id}",
            debug_type=DebugType.EXECUTION,
        )

        return operation.id

    def claim_session(self, session_id: str) -> None:
        if session_id not in self._session_leases:
            self._session_leases[session_id] = SessionLease(session_id)

    async def emit_event(self, event: events.Event) -> None:
        await self._operation_dispatcher.emit_event(event)

    async def _shell_tasks_updated(self, session_id: str, tasks: list[ShellTaskSnapshot]) -> None:
        if not self._stopped:
            manager = getattr(self, "task_manager", None)
            if manager is not None:
                for task in tasks:
                    await manager.record_shell(task, Path(task.work_dir))
                if tasks:
                    await self.emit_event(
                        events.BackgroundTasksUpdatedEvent(
                            session_id=session_id,
                            tasks=await manager.list_tasks(session_id, Path(tasks[0].work_dir)),
                        )
                    )
            await self.emit_event(events.ShellTasksUpdatedEvent(session_id=session_id, tasks=tasks))

    async def _shell_completed(self, task: ShellTaskSnapshot) -> None:
        await self.task_manager.record_shell(task, Path(task.work_dir))

    def current_session_id(self) -> str | None:
        return self._operation_dispatcher.current_session_id()

    @property
    def current_agent(self) -> Agent | None:
        return self._operation_dispatcher.current_agent

    def has_running_tasks(self) -> bool:
        return (
            self.shell_task_manager.has_running_tasks()
            or self._operation_dispatcher.has_running_side_questions()
            or any(not active.task.done() for active in self._operation_dispatcher.list_active_tasks())
        )

    def cancel_auto_away_summary(self, session_id: str) -> None:
        self._operation_dispatcher.cancel_auto_away_summary(session_id)

    async def close_session(self, session_id: str, force: bool = False) -> bool:
        # Side-question answers live outside the actor's task handles, so closing
        # would otherwise leave one writing history for a released session.
        self._operation_dispatcher.cancel_side_questions(session_id)
        await self._operation_dispatcher.stop_auxiliary_tasks(session_id)
        cancelled_requests: list[PendingUserInteractionRequest] = []
        if force:
            # Stop the owner first so it cannot launch another child during teardown.
            actor = self.session_registry.get_session_actor(session_id)
            if actor is not None:
                actor.cancel_queued_runs()
            await self._operation_dispatcher.handle_interrupt(op.InterruptOperation(session_id=session_id))
            await self._operation_dispatcher.handle_stop_sub_agents(op.StopSubAgentsOperation(session_id=session_id))
            cancelled_requests = self.session_registry.cancel_pending_interactions_with_requests(session_id=session_id)

        closed = await self.session_registry.close_session(session_id, force=force)
        if closed:
            await self.shell_task_manager.stop_session(session_id)
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
            lease = self._session_leases.pop(session_id, None)
            if lease is not None:
                lease.close()
        return closed

    async def reclaim_idle_sessions(self, *, idle_for_seconds: float) -> list[str]:
        # Keep the primary session and owners of active tasks in memory.
        exclude: set[str] = self.shell_task_manager.active_session_ids() | self.task_manager.active_owner_ids()
        primary = self._operation_dispatcher.current_session_id()
        if primary is not None:
            exclude.add(primary)
        return await self.session_registry.reclaim_idle_sessions(
            idle_for_seconds=idle_for_seconds, exclude=exclude or None
        )

    async def wait_for(self, operation_id: str) -> Literal["completed", "rejected", "failed"] | None:
        return await self._operation_awaiter.wait_for(operation_id)

    async def submit_and_wait(self, operation: op.Operation) -> None:
        operation_id = await self.submit(operation)
        await self.wait_for(operation_id)

    async def stop(self) -> None:
        self._stopped = True
        await self.task_manager.aclose()
        await self.shell_task_manager.aclose()
        sessions_to_flush: list[Agent] = []
        for runtime in self.session_registry.list_session_actors():
            agent = runtime.get_agent()
            if agent is None:
                continue
            sessions_to_flush.append(agent)

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

        await self._operation_dispatcher.stop_auxiliary_tasks()

        for agent in sessions_to_flush:
            with contextlib.suppress(Exception):
                await agent.session.wait_for_flush()

        await self.session_registry.stop()
        for lease in self._session_leases.values():
            lease.close()
        self._session_leases.clear()
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
            if isinstance(operation, op.StopSubAgentsOperation | op.StopAllTasksOperation):
                # Its failed lifecycle receipt must not end an unrelated root turn.
                raise
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
