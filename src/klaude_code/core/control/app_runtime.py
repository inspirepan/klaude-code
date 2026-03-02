from __future__ import annotations

import asyncio
from collections.abc import Callable

from klaude_code.core.agent.agent import Agent
from klaude_code.core.agent.runtime import LLMClients, OperationExecutor
from klaude_code.core.agent_profile import ModelProfileProvider
from klaude_code.core.control.event_bus import EventBus
from klaude_code.core.control.runtime_hub import RuntimeHub
from klaude_code.core.control.user_interaction import PendingUserInteractionRequest
from klaude_code.log import DebugType, log_debug
from klaude_code.protocol import events, op, user_interaction


class AppRuntime:
    """Runtime entry for CLI/TUI operation submission and lifecycle control."""

    def __init__(
        self,
        event_bus: EventBus,
        llm_clients: LLMClients,
        model_profile_provider: ModelProfileProvider | None = None,
        on_model_change: Callable[[str], None] | None = None,
    ):
        self._operation_executor = OperationExecutor(event_bus, llm_clients, model_profile_provider, on_model_change)
        self.runtime_hub = RuntimeHub(
            handle_operation=self._handle_operation,
            reject_operation=self._reject_operation,
        )
        self._operation_executor.set_close_session_callback(self.close_session)
        self._operation_executor.set_child_task_state_change_callback(self._on_child_task_state_change)
        self._operation_executor.set_user_interaction_callbacks(
            request_callback=self.runtime_hub.request_user_interaction,
            respond_callback=self._respond_user_interaction,
            cancel_callback=self._cancel_pending_user_interactions,
        )
        self._stopped = False
        self._background_tasks: set[asyncio.Task[None]] = set()

    async def _reject_operation(self, operation: op.Operation, active_task_id: str | None) -> None:
        session_id = getattr(operation, "session_id", None)
        if session_id is None:
            raise RuntimeError("Busy rejection requires session-bound operation")

        await self._operation_executor.emit_event(
            events.OperationRejectedEvent(
                session_id=session_id,
                operation_id=operation.id,
                operation_type=operation.type.value,
                reason="session_busy",
                active_task_id=active_task_id,
            )
        )
        self._complete_operation(operation)

    def _on_operation_applied(self, operation: op.Operation) -> None:
        self.runtime_hub.apply_operation_effect(operation)

    def _respond_user_interaction(
        self,
        request_id: str,
        session_id: str,
        response: user_interaction.UserInteractionResponse,
    ) -> None:
        self.runtime_hub.respond_user_interaction(
            request_id=request_id,
            session_id=session_id,
            response=response,
        )

    def _cancel_pending_user_interactions(
        self,
        session_id: str | None,
    ) -> list[PendingUserInteractionRequest]:
        return self.runtime_hub.cancel_pending_interactions_with_requests(session_id=session_id)

    def _on_child_task_state_change(self, session_id: str, task_id: str, is_active: bool) -> None:
        self.runtime_hub.mark_child_task_state(session_id=session_id, task_id=task_id, is_active=is_active)

    def _complete_operation(self, operation: op.Operation) -> None:
        self.runtime_hub.mark_operation_completed(operation.id)

    async def submit(self, operation: op.Operation) -> str:
        if self._stopped:
            raise RuntimeError("AppRuntime is stopped")

        await self.runtime_hub.submit(operation)

        log_debug(
            f"Submitted operation {operation.type} with ID {operation.id}",
            style="blue",
            debug_type=DebugType.EXECUTION,
        )

        return operation.id

    async def emit_event(self, event: events.Event) -> None:
        await self._operation_executor.emit_event(event)

    def current_session_id(self) -> str | None:
        return self._operation_executor.current_session_id()

    @property
    def current_agent(self) -> Agent | None:
        return self._operation_executor.current_agent

    def has_running_tasks(self) -> bool:
        return any(not active.task.done() for active in self._operation_executor.list_active_tasks())

    async def close_session(self, session_id: str, force: bool = False) -> bool:
        closed = await self.runtime_hub.close_session(session_id, force=force)
        if closed:
            self._operation_executor.drop_session_state(session_id)
        return closed

    async def reclaim_idle_sessions(self, *, idle_for_seconds: float) -> list[str]:
        reclaimed = await self.runtime_hub.reclaim_idle_runtimes(idle_for_seconds=idle_for_seconds)
        for session_id in reclaimed:
            self._operation_executor.drop_session_state(session_id)
        return reclaimed

    async def wait_for(self, operation_id: str) -> None:
        await self.runtime_hub.wait_for(operation_id)

    async def submit_and_wait(self, operation: op.Operation) -> None:
        operation_id = await self.submit(operation)
        await self.wait_for(operation_id)

    async def stop(self) -> None:
        self._stopped = True
        cancelled_requests = self._operation_executor.cancel_pending_user_interactions(session_id=None)
        for request in cancelled_requests:
            await self._operation_executor.emit_event(
                events.UserInteractionCancelledEvent(
                    session_id=request.session_id,
                    request_id=request.request_id,
                    reason="shutdown",
                )
            )
            await self._operation_executor.emit_event(
                events.UserInteractionResolvedEvent(
                    session_id=request.session_id,
                    request_id=request.request_id,
                    status="cancelled",
                )
            )

        tasks_to_await: list[asyncio.Task[None]] = []
        for active in self._operation_executor.list_active_tasks():
            task = active.task
            if not task.done():
                task.cancel()
                tasks_to_await.append(task)

        if tasks_to_await:
            await asyncio.gather(*tasks_to_await, return_exceptions=True)

        if self._background_tasks:
            await asyncio.gather(*self._background_tasks, return_exceptions=True)
            self._background_tasks.clear()

        await self.runtime_hub.stop()
        self._operation_executor.clear_active_tasks()

        log_debug("AppRuntime stopped", style="yellow", debug_type=DebugType.EXECUTION)

    async def _handle_operation(self, operation: op.Operation) -> None:
        try:
            log_debug(
                f"Handling operation {operation.id} of type {operation.type.value}",
                style="cyan",
                debug_type=DebugType.EXECUTION,
            )

            await operation.execute(handler=self._operation_executor)
            self._on_operation_applied(operation)

            active_task = self._operation_executor.get_active_task(operation.id)

            async def _await_agent_and_complete(captured_task: asyncio.Task[None]) -> None:
                try:
                    await captured_task
                finally:
                    self._complete_operation(operation)

            if active_task is None:
                self._complete_operation(operation)
            else:
                self.runtime_hub.bind_root_task(operation_id=operation.id, task_id=active_task.task_id)
                background_task = asyncio.create_task(_await_agent_and_complete(active_task.task))
                self._background_tasks.add(background_task)
                background_task.add_done_callback(self._background_tasks.discard)

        except Exception as e:
            log_debug(
                f"Failed to handle operation {operation.id}: {e!s}",
                style="red",
                debug_type=DebugType.EXECUTION,
            )
            session_id = getattr(operation, "session_id", None) or getattr(operation, "target_session_id", None)
            await self._operation_executor.emit_event(
                events.ErrorEvent(
                    error_message=f"Operation failed: {e!s}",
                    can_retry=False,
                    session_id=session_id or "__app__",
                )
            )
            self._complete_operation(operation)
