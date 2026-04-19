"""Operation dispatcher: wiring layer that routes operations to handlers."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal

from klaude_code.agent.agent import Agent
from klaude_code.agent.agent_profile import DefaultModelProfileProvider, ModelProfileProvider
from klaude_code.agent.runtime.agent_ops import (
    ActiveTask,
    AgentOperationHandler,
    AgentRunner,
    BashRunner,
)
from klaude_code.agent.runtime.config_ops import ConfigHandler, ModelSwitcher
from klaude_code.agent.runtime.llm import LLMClients
from klaude_code.agent.runtime.sub_agent import SubAgentExecutor
from klaude_code.control.event_bus import EventBus
from klaude_code.control.runtime.actor import SessionActor
from klaude_code.control.user_interaction import PendingUserInteractionRequest
from klaude_code.protocol import events, op, user_interaction
from klaude_code.protocol.op_handler import OperationHandler


@dataclass(frozen=True)
class OperationDispatcherPorts:
    ensure_session_actor: Callable[[str], SessionActor]
    get_session_actor: Callable[[str], SessionActor | None]
    get_session_actor_for_operation: Callable[[str], SessionActor | None]
    list_session_actors: Callable[[], list[SessionActor]]
    register_task: Callable[[str, str, str, asyncio.Task[None]], None]
    remove_task: Callable[[str, str], None]
    close_session: Callable[[str, bool], Awaitable[bool]]
    request_user_interaction: Callable[
        [PendingUserInteractionRequest],
        Awaitable[user_interaction.UserInteractionResponse],
    ]
    respond_user_interaction: Callable[[str, str, user_interaction.UserInteractionResponse], None]
    cancel_pending_interactions: Callable[[str | None], list[PendingUserInteractionRequest]]
    on_child_task_state_change: Callable[[str, str, bool], None]

class EventPublisher:
    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus

    async def publish(
        self,
        event: events.Event,
        *,
        operation_id: str | None = None,
        task_id: str | None = None,
        causation_id: str | None = None,
    ) -> None:
        await self._event_bus.publish(
            event,
            operation_id=operation_id,
            task_id=task_id,
            causation_id=causation_id,
        )

class OperationDispatcher:
    """
    Context object providing shared state and operation handlers.

    This context is passed to operations when they execute, allowing them
    to access shared resources like the event bus and active sessions.

    Implements the OperationHandler protocol via structural subtyping.
    """

    def __init__(
        self,
        event_bus: EventBus,
        llm_clients: LLMClients,
        ports: OperationDispatcherPorts,
        model_profile_provider: ModelProfileProvider | None = None,
        on_model_change: Callable[[str], None] | None = None,
    ):
        self._event_publisher = EventPublisher(event_bus)
        self.llm_clients: LLMClients = llm_clients
        self._ports = ports

        resolved_profile_provider = model_profile_provider or DefaultModelProfileProvider()
        self.model_profile_provider: ModelProfileProvider = resolved_profile_provider

        self._sub_agent_executor = SubAgentExecutor(self.emit_event, llm_clients, resolved_profile_provider)
        self._agent_operation_handler = AgentOperationHandler(
            emit_event=self.emit_event,
            llm_clients=llm_clients,
            model_profile_provider=resolved_profile_provider,
            sub_agent_manager=self._sub_agent_executor,
            on_child_task_state_change=self._on_child_task_state_change,
            ensure_session_actor=ports.ensure_session_actor,
            get_session_actor=ports.get_session_actor,
            get_session_actor_for_operation=ports.get_session_actor_for_operation,
            list_session_actors=ports.list_session_actors,
            register_task=ports.register_task,
            remove_task=ports.remove_task,
            request_user_interaction=self.request_user_interaction,
        )
        self._model_switcher = ModelSwitcher(resolved_profile_provider)
        self._agent_runner = AgentRunner(self._agent_operation_handler)
        self._bash_runner = BashRunner(self._agent_operation_handler)
        self._config_handler = ConfigHandler(
            agent_runner=self._agent_runner,
            model_switcher=self._model_switcher,
            emit_event=self.emit_event,
            request_user_interaction=self._request_operation_user_interaction,
            current_session_id=self.current_session_id,
            on_model_change=on_model_change,
        )

    async def _request_operation_user_interaction(
        self,
        session_id: str,
        request_id: str,
        source: user_interaction.UserInteractionSource,
        payload: user_interaction.UserInteractionRequestPayload,
    ) -> user_interaction.UserInteractionResponse:
        return await self.request_user_interaction(
            PendingUserInteractionRequest(
                request_id=request_id,
                session_id=session_id,
                source=source,
                tool_call_id=None,
                payload=payload,
            )
        )

    async def request_user_interaction(
        self,
        request: PendingUserInteractionRequest,
    ) -> user_interaction.UserInteractionResponse:
        await self.emit_event(
            events.UserInteractionRequestEvent(
                session_id=request.session_id,
                request_id=request.request_id,
                source=request.source,
                tool_call_id=request.tool_call_id,
                payload=request.payload,
            )
        )
        return await self._ports.request_user_interaction(request)

    def cancel_pending_user_interactions(self, *, session_id: str | None) -> list[PendingUserInteractionRequest]:
        return self._ports.cancel_pending_interactions(session_id)

    async def _emit_interaction_cancelled_events(
        self,
        requests: list[PendingUserInteractionRequest],
        *,
        reason: Literal["user_cancelled", "interrupt", "shutdown", "session_close"],
    ) -> None:
        for request in requests:
            await self.emit_event(
                events.UserInteractionCancelledEvent(
                    session_id=request.session_id,
                    request_id=request.request_id,
                    reason=reason,
                ),
                causation_id=request.request_id,
            )
            await self.emit_event(
                events.UserInteractionResolvedEvent(
                    session_id=request.session_id,
                    request_id=request.request_id,
                    status="cancelled",
                ),
                causation_id=request.request_id,
            )

    def _on_child_task_state_change(self, session_id: str, task_id: str, is_active: bool) -> None:
        self._ports.on_child_task_state_change(session_id, task_id, is_active)

    async def emit_event(
        self,
        event: events.Event,
        *,
        operation_id: str | None = None,
        task_id: str | None = None,
        causation_id: str | None = None,
    ) -> None:
        """Publish an event to the runtime event bus."""
        await self._event_publisher.publish(
            event,
            operation_id=operation_id,
            task_id=task_id,
            causation_id=causation_id,
        )

    def current_session_id(self) -> str | None:
        """Return the primary active session id, if any.

        This is a convenience wrapper used by the CLI, which conceptually
        operates on a single interactive session per process.
        """

        return self._agent_runner.current_session_id()

    @property
    def current_agent(self) -> Agent | None:
        """Return the currently active agent, if any."""

        return self._agent_runner.current_agent

    async def handle_init_agent(self, operation: op.InitAgentOperation) -> None:
        """Initialize an agent for a session and replay history to UI."""
        await self._agent_runner.init_agent(operation.session_id, work_dir=operation.work_dir)

    async def handle_run_agent(self, operation: op.RunAgentOperation) -> None:
        await self._agent_runner.run_agent(operation)

    async def handle_run_bash(self, operation: op.RunBashOperation) -> None:
        await self._bash_runner.run_bash(operation)

    async def handle_continue_agent(self, operation: op.ContinueAgentOperation) -> None:
        await self._agent_runner.continue_agent(operation)

    async def handle_compact_session(self, operation: op.CompactSessionOperation) -> None:
        await self._agent_runner.compact_session(operation)

    async def handle_generate_away_summary(self, operation: op.GenerateAwaySummaryOperation) -> None:
        await self._agent_runner.generate_away_summary(operation)

    async def handle_change_model(self, operation: op.ChangeModelOperation) -> None:
        await self._config_handler.handle_change_model(operation)

    async def handle_change_thinking(self, operation: op.ChangeThinkingOperation) -> None:
        await self._config_handler.handle_change_thinking(operation)

    async def handle_change_sub_agent_model(self, operation: op.ChangeSubAgentModelOperation) -> None:
        await self._config_handler.handle_change_sub_agent_model(operation)

    async def handle_change_compact_model(self, operation: op.ChangeCompactModelOperation) -> None:
        await self._config_handler.handle_change_compact_model(operation)

    async def handle_request_model(self, operation: op.RequestModelOperation) -> None:
        await self._config_handler.handle_request_model(operation)

    async def handle_request_thinking(self, operation: op.RequestThinkingOperation) -> None:
        await self._config_handler.handle_request_thinking(operation)

    async def handle_request_sub_agent_model(self, operation: op.RequestSubAgentModelOperation) -> None:
        await self._config_handler.handle_request_sub_agent_model(operation)

    async def handle_get_session_stats(self, operation: op.GetSessionStatsOperation) -> None:
        await self._config_handler.handle_get_session_stats(operation)

    async def handle_clear_session(self, operation: op.ClearSessionOperation) -> None:
        await self._agent_runner.clear_session(operation.session_id)

    async def handle_fork_and_switch_session(self, operation: op.ForkAndSwitchSessionOperation) -> None:
        await self._agent_runner.fork_and_switch_session(
            session_id=operation.session_id,
            new_session_id=operation.new_session_id,
            original_session_short_id=operation.original_session_short_id,
        )

    async def handle_interrupt(self, operation: op.InterruptOperation) -> None:
        """Handle an interrupt by invoking agent.on_interrupt() and cancelling tasks."""

        await self._agent_runner.interrupt(operation.session_id)
        cancelled_requests = self.cancel_pending_user_interactions(session_id=operation.session_id)
        await self._emit_interaction_cancelled_events(cancelled_requests, reason="interrupt")

    async def handle_close_session(self, operation: op.CloseSessionOperation) -> None:
        await self._ports.close_session(operation.session_id, operation.force)

    async def handle_user_interaction_respond(self, operation: op.UserInteractionRespondOperation) -> None:
        self._ports.respond_user_interaction(operation.request_id, operation.session_id, operation.response)
        await self.emit_event(
            events.UserInteractionResponseReceivedEvent(
                session_id=operation.session_id,
                request_id=operation.request_id,
                status=operation.response.status,
            ),
            causation_id=operation.request_id,
        )
        if operation.response.status == "cancelled":
            await self.emit_event(
                events.UserInteractionCancelledEvent(
                    session_id=operation.session_id,
                    request_id=operation.request_id,
                    reason="user_cancelled",
                ),
                causation_id=operation.request_id,
            )
        await self.emit_event(
            events.UserInteractionResolvedEvent(
                session_id=operation.session_id,
                request_id=operation.request_id,
                status=operation.response.status,
            ),
            causation_id=operation.request_id,
        )

    def get_active_task(self, operation_id: str) -> ActiveTask | None:
        """Return the active runtime task for an operation id if present."""

        return self._agent_runner.get_active_task(operation_id)

    def list_active_tasks(self) -> list[ActiveTask]:
        return self._agent_runner.list_active_tasks()

    def clear_active_tasks(self) -> None:
        self._agent_runner.clear_active_tasks()

# Static type check: OperationDispatcher must satisfy OperationHandler protocol.
# If this line causes a type error, OperationDispatcher is missing required methods.
_: type[OperationHandler] = OperationDispatcher
