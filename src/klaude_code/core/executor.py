"""
Executor module providing the core event loop and task management.

This module implements the submission_loop equivalent for klaude,
handling operations submitted from the CLI and coordinating with agents.
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from klaude_code.config import load_config
from klaude_code.config.sub_agent_model_helper import SubAgentModelHelper
from klaude_code.core.agent import Agent
from klaude_code.core.agent_profile import DefaultModelProfileProvider, ModelProfileProvider
from klaude_code.core.bash_mode import run_bash_command
from klaude_code.core.compaction import CompactionReason, run_compaction
from klaude_code.core.event_bus import EventBus
from klaude_code.core.loaded_skills import (
    get_loaded_skill_names_by_location,
    get_loaded_skill_warnings_by_location,
)
from klaude_code.core.manager import LLMClients, SubAgentManager
from klaude_code.core.memory import get_existing_memory_paths_by_location
from klaude_code.core.runtime_hub import RuntimeHub
from klaude_code.core.user_interaction import PendingUserInteractionRequest
from klaude_code.llm.registry import create_llm_client
from klaude_code.log import DebugType, log_debug
from klaude_code.protocol import commands, events, message, model, op, user_interaction
from klaude_code.protocol.llm_param import LLMConfigParameter, Thinking
from klaude_code.protocol.op_handler import OperationHandler
from klaude_code.protocol.sub_agent import SubAgentResult, get_sub_agent_profile
from klaude_code.session.export import build_export_html, get_default_export_path
from klaude_code.session.session import Session


@dataclass
class ActiveTask:
    """Track an in-flight runtime task."""

    task_id: str
    operation_id: str
    task: asyncio.Task[None]
    session_id: str


class TaskManager:
    """Manager that tracks active tasks and operation/task mappings."""

    def __init__(self) -> None:
        self._tasks: dict[str, ActiveTask] = {}
        self._operation_task_ids: dict[str, str] = {}

    def register(self, *, operation_id: str, task_id: str, task: asyncio.Task[None], session_id: str) -> None:
        """Register a new active task for an operation."""

        self._tasks[task_id] = ActiveTask(
            task_id=task_id,
            operation_id=operation_id,
            task=task,
            session_id=session_id,
        )
        self._operation_task_ids[operation_id] = task_id

    def get_by_operation(self, operation_id: str) -> ActiveTask | None:
        """Return the active task for an operation id if present."""

        task_id = self._operation_task_ids.get(operation_id)
        if task_id is None:
            return None
        return self._tasks.get(task_id)

    def remove(self, task_id: str) -> None:
        """Remove the active task associated with a task id if present."""

        active = self._tasks.pop(task_id, None)
        if active is None:
            return

        current = self._operation_task_ids.get(active.operation_id)
        if current == task_id:
            self._operation_task_ids.pop(active.operation_id, None)

    def values(self) -> list[ActiveTask]:
        """Return a snapshot list of all active tasks."""

        return list(self._tasks.values())

    def cancel_tasks_for_sessions(self, session_ids: set[str] | None = None) -> list[tuple[str, asyncio.Task[None]]]:
        """Collect tasks that should be cancelled for given sessions."""

        tasks_to_cancel: list[tuple[str, asyncio.Task[None]]] = []
        for task_id, active in list(self._tasks.items()):
            task = active.task
            if task.done():
                continue
            if session_ids is None or active.session_id in session_ids:
                tasks_to_cancel.append((task_id, task))
        return tasks_to_cancel

    def clear(self) -> None:
        """Remove all tracked tasks from the manager."""

        self._tasks.clear()
        self._operation_task_ids.clear()


class AgentRuntime:
    """Coordinate agent lifecycle and in-flight tasks for the executor."""

    def __init__(
        self,
        *,
        emit_event: Callable[[events.Event], Awaitable[None]],
        llm_clients: LLMClients,
        model_profile_provider: ModelProfileProvider,
        task_manager: TaskManager,
        sub_agent_manager: SubAgentManager,
        request_user_interaction: Callable[
            [PendingUserInteractionRequest],
            Awaitable[user_interaction.UserInteractionResponse],
        ],
    ) -> None:
        self._emit_event = emit_event
        self._llm_clients = llm_clients
        self._model_profile_provider = model_profile_provider
        self._task_manager = task_manager
        self._sub_agent_manager = sub_agent_manager
        self._request_user_interaction_callback = request_user_interaction
        self._agents: dict[str, Agent] = {}
        self._primary_session_id: str | None = None

    async def _request_user_interaction(
        self,
        session_id: str,
        request_id: str,
        source: user_interaction.UserInteractionSource,
        payload: user_interaction.UserInteractionRequestPayload,
        tool_call_id: str | None,
    ) -> user_interaction.UserInteractionResponse:
        if source != "tool":
            raise ValueError("Only tool-based user interactions are supported in this context")
        agent = self._agents.get(session_id)
        if agent is None:
            raise RuntimeError("No active agent session")
        if agent.session.sub_agent_state is not None:
            raise RuntimeError("User interaction is available only for the main agent")
        return await self._request_user_interaction_callback(
            PendingUserInteractionRequest(
                request_id=request_id,
                session_id=session_id,
                source=source,
                tool_call_id=tool_call_id,
                payload=payload,
            )
        )

    def _build_request_user_interaction_callback(
        self,
        *,
        session_id: str,
    ) -> Callable[
        [
            str,
            user_interaction.UserInteractionSource,
            user_interaction.UserInteractionRequestPayload,
            str | None,
        ],
        Awaitable[user_interaction.UserInteractionResponse],
    ]:
        async def _callback(
            request_id: str,
            source: user_interaction.UserInteractionSource,
            payload: user_interaction.UserInteractionRequestPayload,
            tool_call_id: str | None,
        ) -> user_interaction.UserInteractionResponse:
            return await self._request_user_interaction(
                session_id,
                request_id,
                source,
                payload,
                tool_call_id,
            )

        return _callback

    def current_session_id(self) -> str | None:
        session_id = self._primary_session_id
        if session_id is None:
            return None
        if session_id not in self._agents:
            self._primary_session_id = None
            return None
        return session_id

    @property
    def current_agent(self) -> Agent | None:
        session_id = self.current_session_id()
        if session_id is None:
            return None
        return self._agents.get(session_id)

    def drop_session(self, session_id: str) -> None:
        self._agents.pop(session_id, None)
        if self._primary_session_id != session_id:
            return
        self._primary_session_id = next(iter(self._agents), None)

    async def ensure_agent(self, session_id: str | None = None) -> Agent:
        """Return the agent for a session, creating or loading as needed."""

        if session_id is not None:
            existing = self._agents.get(session_id)
            if existing is not None:
                return existing

        session = Session.create() if session_id is None else Session.load(session_id)

        existing = self._agents.get(session.id)
        if existing is not None:
            return existing

        if (
            session.model_thinking is not None
            and session.model_name
            and session.model_name == self._llm_clients.main.model_name
        ):
            self._llm_clients.main.get_llm_config().thinking = session.model_thinking

        profile = self._model_profile_provider.build_profile(self._llm_clients.main)
        agent = Agent(
            session=session,
            profile=profile,
            compact_llm_client=self._llm_clients.compact,
            request_user_interaction=self._build_request_user_interaction_callback(session_id=session.id),
        )

        await self._emit_event(
            events.WelcomeEvent(
                session_id=session.id,
                work_dir=str(session.work_dir),
                llm_config=self._llm_clients.main.get_llm_config(),
                loaded_skills=get_loaded_skill_names_by_location(),
                loaded_skill_warnings=get_loaded_skill_warnings_by_location(),
                loaded_memories=get_existing_memory_paths_by_location(work_dir=session.work_dir),
            )
        )

        async for evt in agent.replay_history():
            await self._emit_event(evt)

        self._agents[session.id] = agent
        if self._primary_session_id is None:
            self._primary_session_id = session.id
        log_debug(
            f"Initialized agent for session: {session.id}",
            style="cyan",
            debug_type=DebugType.EXECUTION,
        )
        return agent

    async def init_agent(self, session_id: str | None) -> None:
        agent = await self.ensure_agent(session_id)
        self._primary_session_id = agent.session.id

    async def run_agent(self, operation: op.RunAgentOperation) -> None:
        agent = await self.ensure_agent(operation.session_id)
        agent.session.append_history(
            [
                message.UserMessage(
                    parts=message.parts_from_text_and_images(
                        operation.input.text,
                        operation.input.images,
                    )
                )
            ]
        )

        existing_active = self._task_manager.get_by_operation(operation.id)
        if existing_active is not None and not existing_active.task.done():
            raise RuntimeError(f"Active task already registered for operation {operation.id}")

        task_id = uuid4().hex
        task: asyncio.Task[None] = asyncio.create_task(
            self._run_agent_task(agent, operation.input, task_id, operation.session_id)
        )
        self._task_manager.register(
            operation_id=operation.id,
            task_id=task_id,
            task=task,
            session_id=operation.session_id,
        )

    async def run_bash(self, operation: op.RunBashOperation) -> None:
        agent = await self.ensure_agent(operation.session_id)

        existing_active = self._task_manager.get_by_operation(operation.id)
        if existing_active is not None and not existing_active.task.done():
            raise RuntimeError(f"Active task already registered for operation {operation.id}")

        task_id = uuid4().hex
        task: asyncio.Task[None] = asyncio.create_task(
            self._run_bash_task(
                session=agent.session,
                command=operation.command,
                task_id=task_id,
                session_id=operation.session_id,
            )
        )
        self._task_manager.register(
            operation_id=operation.id,
            task_id=task_id,
            task=task,
            session_id=operation.session_id,
        )

    async def continue_agent(self, operation: op.ContinueAgentOperation) -> None:
        """Continue agent execution without adding a new user message."""
        agent = await self.ensure_agent(operation.session_id)

        existing_active = self._task_manager.get_by_operation(operation.id)
        if existing_active is not None and not existing_active.task.done():
            raise RuntimeError(f"Active task already registered for operation {operation.id}")

        # Use empty input since we're continuing from existing history
        empty_input = message.UserInputPayload(text="")
        task_id = uuid4().hex
        task: asyncio.Task[None] = asyncio.create_task(
            self._run_agent_task(agent, empty_input, task_id, operation.session_id)
        )
        self._task_manager.register(
            operation_id=operation.id,
            task_id=task_id,
            task=task,
            session_id=operation.session_id,
        )

    async def compact_session(self, operation: op.CompactSessionOperation) -> None:
        agent = await self.ensure_agent(operation.session_id)

        if self._task_manager.cancel_tasks_for_sessions({operation.session_id}):
            await self.interrupt(operation.session_id)

        existing_active = self._task_manager.get_by_operation(operation.id)
        if existing_active is not None and not existing_active.task.done():
            raise RuntimeError(f"Active task already registered for operation {operation.id}")

        task_id = uuid4().hex
        task: asyncio.Task[None] = asyncio.create_task(
            self._run_compaction_task(agent, operation, task_id, operation.session_id)
        )
        self._task_manager.register(
            operation_id=operation.id,
            task_id=task_id,
            task=task,
            session_id=operation.session_id,
        )

    async def clear_session(self, session_id: str) -> None:
        agent = await self.ensure_agent(session_id)
        old_session_id = agent.session.id
        new_session = Session.create(work_dir=agent.session.work_dir)
        new_session.model_name = agent.session.model_name
        new_session.model_config_name = agent.session.model_config_name
        new_session.model_thinking = agent.session.model_thinking

        new_agent = Agent(
            session=new_session,
            profile=agent.profile,
            compact_llm_client=agent.compact_llm_client,
            request_user_interaction=self._build_request_user_interaction_callback(session_id=new_session.id),
        )
        self._agents.pop(old_session_id, None)
        self._agents[new_session.id] = new_agent
        if self._primary_session_id == old_session_id:
            self._primary_session_id = new_session.id

        await self._emit_event(
            events.CommandOutputEvent(
                session_id=new_agent.session.id,
                command_name=commands.CommandName.NEW,
                content="started new conversation",
            )
        )
        await self._emit_event(
            events.WelcomeEvent(
                session_id=new_agent.session.id,
                work_dir=str(new_agent.session.work_dir),
                llm_config=self._llm_clients.main.get_llm_config(),
                loaded_skills=get_loaded_skill_names_by_location(),
                loaded_skill_warnings=get_loaded_skill_warnings_by_location(),
                loaded_memories=get_existing_memory_paths_by_location(work_dir=new_agent.session.work_dir),
            )
        )

    async def interrupt(self, target_session_id: str | None) -> None:
        if target_session_id is not None:
            session_ids = [target_session_id]
        else:
            session_ids = sorted({active.session_id for active in self._task_manager.values()})
            if self._primary_session_id is not None and self._primary_session_id not in session_ids:
                session_ids.append(self._primary_session_id)

        for sid in session_ids:
            agent = self._agents.get(sid)
            if agent is not None:
                for evt in agent.on_interrupt():
                    await self._emit_event(evt)

        await self._emit_event(events.InterruptEvent(session_id=target_session_id or "all"))

        if target_session_id is None:
            session_filter: set[str] | None = None
        else:
            session_filter = {target_session_id}

        tasks_to_cancel = self._task_manager.cancel_tasks_for_sessions(session_filter)

        scope = target_session_id or "all"
        log_debug(
            f"Interrupting {len(tasks_to_cancel)} task(s) for: {scope}",
            style="yellow",
            debug_type=DebugType.EXECUTION,
        )

        for task_id, task in tasks_to_cancel:
            task.cancel()
            self._task_manager.remove(task_id)

    async def _run_agent_task(
        self,
        agent: Agent,
        user_input: message.UserInputPayload,
        task_id: str,
        session_id: str,
    ) -> None:
        try:
            log_debug(
                f"Starting agent task {task_id} for session {session_id}",
                style="green",
                debug_type=DebugType.EXECUTION,
            )

            async def _runner(
                state: model.SubAgentState,
                record_session_id: Callable[[str], None] | None,
                register_metadata_getter: Callable[[Callable[[], model.TaskMetadata | None]], None] | None,
                register_progress_getter: Callable[[Callable[[], str | None]], None] | None,
            ) -> SubAgentResult:
                return await self._sub_agent_manager.run_sub_agent(
                    agent,
                    state,
                    record_session_id=record_session_id,
                    register_metadata_getter=register_metadata_getter,
                    register_progress_getter=register_progress_getter,
                )

            async for event in agent.run_task(user_input, run_subtask=_runner):
                await self._emit_event(event)

        except asyncio.CancelledError:
            log_debug(
                f"Agent task {task_id} was cancelled",
                style="yellow",
                debug_type=DebugType.EXECUTION,
            )
            await self._emit_event(events.TaskFinishEvent(session_id=session_id, task_result="task cancelled"))

        except Exception as e:
            import traceback

            log_debug(
                f"Agent task {task_id} failed: {e!s}",
                style="red",
                debug_type=DebugType.EXECUTION,
            )
            log_debug(traceback.format_exc(), style="red", debug_type=DebugType.EXECUTION)
            await self._emit_event(
                events.ErrorEvent(
                    error_message=f"Agent task failed: [{e.__class__.__name__}] {e!s} {traceback.format_exc()}",
                    can_retry=False,
                    session_id=session_id,
                )
            )
        finally:
            self._task_manager.remove(task_id)
            log_debug(
                f"Cleaned up agent task {task_id}",
                style="cyan",
                debug_type=DebugType.EXECUTION,
            )

    async def _run_bash_task(self, *, session: Session, command: str, task_id: str, session_id: str) -> None:
        try:
            await run_bash_command(
                emit_event=self._emit_event,
                session=session,
                session_id=session_id,
                command=command,
            )
        finally:
            self._task_manager.remove(task_id)

    async def _run_compaction_task(
        self,
        agent: Agent,
        operation: op.CompactSessionOperation,
        task_id: str,
        session_id: str,
    ) -> None:
        cancel_event = asyncio.Event()
        reason = operation.reason
        try:
            await self._emit_event(events.CompactionStartEvent(session_id=session_id, reason=reason))
            log_debug(f"[Compact:{reason}] start", debug_type=DebugType.RESPONSE)
            compact_client = self._llm_clients.get_compact_client()
            result = await run_compaction(
                session=agent.session,
                reason=CompactionReason(reason),
                focus=operation.focus,
                llm_client=compact_client,
                llm_config=compact_client.get_llm_config(),
                cancel=cancel_event,
            )
            log_debug(f"[Compact:{reason}] result", str(result.to_entry()), debug_type=DebugType.RESPONSE)
            agent.session.append_history([result.to_entry()])
            await self._emit_event(
                events.CompactionEndEvent(
                    session_id=session_id,
                    reason=reason,
                    aborted=False,
                    will_retry=operation.will_retry,
                    tokens_before=result.tokens_before,
                    kept_from_index=result.first_kept_index,
                    summary=result.summary,
                    kept_items_brief=result.kept_items_brief,
                )
            )
        except asyncio.CancelledError:
            cancel_event.set()
            await self._emit_event(
                events.CompactionEndEvent(
                    session_id=session_id,
                    reason=reason,
                    aborted=True,
                    will_retry=operation.will_retry,
                )
            )
            raise
        except Exception as exc:
            import traceback

            log_debug(
                f"[Compact:{reason}] error",
                str(exc.__class__.__name__),
                str(exc),
                traceback.format_exc(),
                debug_type=DebugType.RESPONSE,
            )
            await self._emit_event(
                events.CompactionEndEvent(
                    session_id=session_id,
                    reason=reason,
                    aborted=True,
                    will_retry=operation.will_retry,
                )
            )
            await self._emit_event(
                events.ErrorEvent(
                    error_message=f"Compaction failed: {exc!s}",
                    can_retry=False,
                    session_id=session_id,
                )
            )
        finally:
            self._task_manager.remove(task_id)

class ModelSwitcher:
    """Apply model changes to an agent session."""

    def __init__(self, model_profile_provider: ModelProfileProvider) -> None:
        self._model_profile_provider = model_profile_provider

    async def change_model(
        self,
        agent: Agent,
        *,
        model_name: str,
        save_as_default: bool,
    ) -> tuple[LLMConfigParameter, str]:
        config = load_config()
        llm_config = config.get_model_config(model_name)
        llm_client = create_llm_client(llm_config)
        agent.set_model_profile(self._model_profile_provider.build_profile(llm_client))

        agent.session.model_config_name = model_name
        agent.session.model_thinking = llm_config.thinking

        if save_as_default:
            config.main_model = model_name
            await config.save()

        return llm_config, model_name

    def change_thinking(self, agent: Agent, *, thinking: Thinking) -> Thinking | None:
        """Apply thinking configuration to the agent's active LLM config and persisted session."""

        config = agent.profile.llm_client.get_llm_config()
        previous = config.thinking
        config.thinking = thinking
        agent.session.model_thinking = thinking
        return previous


class ExecutorContext:
    """
    Context object providing shared state and operations for the executor.

    This context is passed to operations when they execute, allowing them
    to access shared resources like the event bus and active sessions.

    Implements the OperationHandler protocol via structural subtyping.
    """

    def __init__(
        self,
        event_bus: EventBus,
        llm_clients: LLMClients,
        model_profile_provider: ModelProfileProvider | None = None,
        on_model_change: Callable[[str], None] | None = None,
    ):
        self.event_bus = event_bus
        self.llm_clients: LLMClients = llm_clients

        resolved_profile_provider = model_profile_provider or DefaultModelProfileProvider()
        self.model_profile_provider: ModelProfileProvider = resolved_profile_provider

        self.task_manager = TaskManager()
        self.sub_agent_manager = SubAgentManager(self.emit_event, llm_clients, resolved_profile_provider)
        self._on_model_change = on_model_change
        self._close_session_callback: Callable[[str, bool], Awaitable[bool]] | None = None
        self._request_user_interaction_callback: (
            Callable[
                [PendingUserInteractionRequest],
                Awaitable[user_interaction.UserInteractionResponse],
            ]
            | None
        ) = None
        self._respond_user_interaction_callback: (
            Callable[[str, str, user_interaction.UserInteractionResponse], None] | None
        ) = None
        self._cancel_pending_interactions_callback: Callable[[str | None], bool] | None = None
        self._agent_runtime = AgentRuntime(
            emit_event=self.emit_event,
            llm_clients=llm_clients,
            model_profile_provider=resolved_profile_provider,
            task_manager=self.task_manager,
            sub_agent_manager=self.sub_agent_manager,
            request_user_interaction=self.request_user_interaction,
        )
        self._model_switcher = ModelSwitcher(resolved_profile_provider)

    def set_close_session_callback(self, callback: Callable[[str, bool], Awaitable[bool]]) -> None:
        self._close_session_callback = callback

    def set_user_interaction_callbacks(
        self,
        *,
        request_callback: Callable[
            [PendingUserInteractionRequest],
            Awaitable[user_interaction.UserInteractionResponse],
        ],
        respond_callback: Callable[[str, str, user_interaction.UserInteractionResponse], None],
        cancel_callback: Callable[[str | None], bool],
    ) -> None:
        self._request_user_interaction_callback = request_callback
        self._respond_user_interaction_callback = respond_callback
        self._cancel_pending_interactions_callback = cancel_callback

    async def request_user_interaction(
        self,
        request: PendingUserInteractionRequest,
    ) -> user_interaction.UserInteractionResponse:
        callback = self._request_user_interaction_callback
        if callback is None:
            raise RuntimeError("request user interaction callback is not configured")

        await self.emit_event(
            events.UserInteractionRequestEvent(
                session_id=request.session_id,
                request_id=request.request_id,
                source=request.source,
                tool_call_id=request.tool_call_id,
                payload=request.payload,
            )
        )
        return await callback(request)

    def cancel_pending_user_interactions(self, *, session_id: str | None) -> bool:
        callback = self._cancel_pending_interactions_callback
        if callback is None:
            return False
        return callback(session_id)

    async def emit_event(self, event: events.Event) -> None:
        """Publish an event to the runtime event bus."""
        await self.event_bus.publish(event)

    def current_session_id(self) -> str | None:
        """Return the primary active session id, if any.

        This is a convenience wrapper used by the CLI, which conceptually
        operates on a single interactive session per process.
        """

        return self._agent_runtime.current_session_id()

    @property
    def current_agent(self) -> Agent | None:
        """Return the currently active agent, if any."""

        return self._agent_runtime.current_agent

    def drop_session_state(self, session_id: str) -> None:
        self._agent_runtime.drop_session(session_id)

    async def handle_init_agent(self, operation: op.InitAgentOperation) -> None:
        """Initialize an agent for a session and replay history to UI."""
        await self._agent_runtime.init_agent(operation.session_id)

    async def handle_run_agent(self, operation: op.RunAgentOperation) -> None:
        await self._agent_runtime.run_agent(operation)

    async def handle_run_bash(self, operation: op.RunBashOperation) -> None:
        await self._agent_runtime.run_bash(operation)

    async def handle_continue_agent(self, operation: op.ContinueAgentOperation) -> None:
        await self._agent_runtime.continue_agent(operation)

    async def handle_compact_session(self, operation: op.CompactSessionOperation) -> None:
        await self._agent_runtime.compact_session(operation)

    async def handle_change_model(self, operation: op.ChangeModelOperation) -> None:
        agent = await self._agent_runtime.ensure_agent(operation.session_id)
        llm_config, llm_client_name = await self._model_switcher.change_model(
            agent,
            model_name=operation.model_name,
            save_as_default=operation.save_as_default,
        )

        if operation.emit_switch_message:
            default_note = " (saved as default)" if operation.save_as_default else ""
            await self.emit_event(
                events.CommandOutputEvent(
                    session_id=agent.session.id,
                    command_name=commands.CommandName.MODEL,
                    content=f"Switched to: {llm_config.model_id}{default_note}",
                )
            )

        if self._on_model_change is not None:
            self._on_model_change(llm_client_name)

        if operation.emit_welcome_event:
            await self.emit_event(
                events.WelcomeEvent(
                    session_id=agent.session.id,
                    llm_config=llm_config,
                    work_dir=str(agent.session.work_dir),
                    show_klaude_code_info=False,
                )
            )

    async def handle_change_thinking(self, operation: op.ChangeThinkingOperation) -> None:
        """Handle a change thinking operation.

        Interactive thinking selection must happen in the UI/CLI layer. Core only
        applies a concrete thinking configuration.
        """
        agent = await self._agent_runtime.ensure_agent(operation.session_id)

        def _format_thinking_for_display(thinking: Thinking | None) -> str:
            if thinking is None:
                return "not configured"
            if thinking.reasoning_effort:
                return f"reasoning_effort={thinking.reasoning_effort}"
            if thinking.type == "disabled":
                return "off"
            if thinking.type == "enabled":
                if thinking.budget_tokens is None:
                    return "enabled"
                return f"enabled (budget_tokens={thinking.budget_tokens})"
            return "not set"

        if operation.thinking is None:
            raise ValueError("thinking must be provided; interactive selection belongs to UI")

        previous = self._model_switcher.change_thinking(agent, thinking=operation.thinking)
        current = _format_thinking_for_display(previous)
        new_status = _format_thinking_for_display(operation.thinking)

        if operation.emit_switch_message:
            await self.emit_event(
                events.CommandOutputEvent(
                    session_id=agent.session.id,
                    command_name=commands.CommandName.THINKING,
                    content=f"Thinking changed: {current} -> {new_status}",
                )
            )

        if operation.emit_welcome_event:
            await self.emit_event(
                events.WelcomeEvent(
                    session_id=agent.session.id,
                    work_dir=str(agent.session.work_dir),
                    llm_config=agent.profile.llm_client.get_llm_config(),
                    show_klaude_code_info=False,
                )
            )

    async def handle_change_sub_agent_model(self, operation: op.ChangeSubAgentModelOperation) -> None:
        """Handle a change sub-agent model operation."""
        agent = await self._agent_runtime.ensure_agent(operation.session_id)
        config = load_config()

        helper = SubAgentModelHelper(config)

        sub_agent_type = operation.sub_agent_type
        model_name = operation.model_name

        if model_name is None:
            # Clear explicit override and revert to sub-agent default behavior.
            behavior = helper.describe_empty_model_config_behavior(
                sub_agent_type,
                main_model_name=self.llm_clients.main.model_name,
            )

            # Default: inherit from Agent/main client behavior.
            self.llm_clients.sub_clients.pop(sub_agent_type, None)

            display_model = f"({behavior.description})"
        else:
            # Create new client for the sub-agent
            llm_config = config.get_model_config(model_name)
            new_client = create_llm_client(llm_config)
            self.llm_clients.sub_clients[sub_agent_type] = new_client
            display_model = new_client.model_name

        if operation.save_as_default:
            profile = get_sub_agent_profile(sub_agent_type)
            role_key = profile.invoker_type
            if role_key is None:
                raise ValueError(f"Sub-agent '{sub_agent_type}' cannot be configured via sub_agent_models")
            if model_name is None:
                # Remove from config to inherit
                config.sub_agent_models.pop(role_key, None)
            else:
                config.sub_agent_models[role_key] = model_name
            await config.save()

        saved_note = " (saved in ~/.klaude/klaude-config.yaml)" if operation.save_as_default else ""
        await self.emit_event(
            events.CommandOutputEvent(
                session_id=agent.session.id,
                command_name=commands.CommandName.SUB_AGENT_MODEL,
                content=f"{sub_agent_type} model: {display_model}{saved_note}",
            )
        )

    async def handle_change_compact_model(self, operation: op.ChangeCompactModelOperation) -> None:
        """Handle a change compact model operation."""
        agent = await self._agent_runtime.ensure_agent(operation.session_id)
        config = load_config()

        model_name = operation.model_name

        if model_name is None:
            # Clear explicit override and use main client for compaction
            self.llm_clients.compact = None
            agent.compact_llm_client = None
            display_model = "(inherit from main agent)"
        else:
            # Create new client for compaction
            llm_config = config.get_model_config(model_name)
            new_client = create_llm_client(llm_config)
            self.llm_clients.compact = new_client
            agent.compact_llm_client = new_client
            display_model = new_client.model_name

        if operation.save_as_default:
            config.compact_model = model_name
            await config.save()

        saved_note = " (saved in ~/.klaude/klaude-config.yaml)" if operation.save_as_default else ""
        await self.emit_event(
            events.CommandOutputEvent(
                session_id=agent.session.id,
                command_name=commands.CommandName.SUB_AGENT_MODEL,
                content=f"Compact model: {display_model}{saved_note}",
            )
        )

    async def handle_clear_session(self, operation: op.ClearSessionOperation) -> None:
        await self._agent_runtime.clear_session(operation.session_id)

    async def handle_export_session(self, operation: op.ExportSessionOperation) -> None:
        agent = await self._agent_runtime.ensure_agent(operation.session_id)
        try:
            output_path = self._resolve_export_output_path(operation.output_path, agent.session)
            html_doc = self._build_export_html(agent)
            await asyncio.to_thread(output_path.parent.mkdir, parents=True, exist_ok=True)
            await asyncio.to_thread(output_path.write_text, html_doc, "utf-8")
            await asyncio.to_thread(self._open_file, output_path)
            await self.emit_event(
                events.CommandOutputEvent(
                    session_id=agent.session.id,
                    command_name=commands.CommandName.EXPORT,
                    content=f"Session exported and opened: {output_path}",
                )
            )
        except Exception as exc:  # pragma: no cover
            import traceback

            await self.emit_event(
                events.CommandOutputEvent(
                    session_id=agent.session.id,
                    command_name=commands.CommandName.EXPORT,
                    content=f"Failed to export session: {exc}\n{traceback.format_exc()}",
                    is_error=True,
                )
            )

    def _resolve_export_output_path(self, raw: str | None, session: Session) -> Path:
        trimmed = (raw or "").strip()
        if trimmed:
            candidate = Path(trimmed).expanduser()
            if not candidate.is_absolute():
                candidate = Path(session.work_dir) / candidate
            if candidate.suffix.lower() != ".html":
                candidate = candidate.with_suffix(".html")
            return candidate
        return get_default_export_path(session)

    def _build_export_html(self, agent: Agent) -> str:
        profile = agent.profile
        system_prompt = (profile.system_prompt if profile else "") or ""
        tool_schemas = profile.tools if profile else []
        model_name = profile.llm_client.model_name if profile else "unknown"
        return build_export_html(agent.session, system_prompt, tool_schemas, model_name)

    def _open_file(self, path: Path) -> None:
        # Select platform-appropriate command
        if sys.platform == "darwin":
            cmd = "open"
        elif sys.platform == "win32":
            cmd = "start"
        else:
            cmd = "xdg-open"

        try:
            # Detach stdin to prevent interference with prompt_toolkit's terminal state
            if sys.platform == "win32":
                # Windows 'start' requires shell=True
                subprocess.run(f'start "" "{path}"', shell=True, stdin=subprocess.DEVNULL, check=True)
            else:
                subprocess.run([cmd, str(path)], stdin=subprocess.DEVNULL, check=True)
        except FileNotFoundError as exc:  # pragma: no cover
            msg = f"`{cmd}` command not found; please open the HTML manually."
            raise RuntimeError(msg) from exc
        except subprocess.CalledProcessError as exc:  # pragma: no cover
            msg = f"Failed to open HTML with `{cmd}`: {exc}"
            raise RuntimeError(msg) from exc

    async def handle_interrupt(self, operation: op.InterruptOperation) -> None:
        """Handle an interrupt by invoking agent.on_interrupt() and cancelling tasks."""

        await self._agent_runtime.interrupt(operation.target_session_id)
        self.cancel_pending_user_interactions(session_id=operation.target_session_id)

    async def handle_close_session(self, operation: op.CloseSessionOperation) -> None:
        if self._close_session_callback is None:
            raise RuntimeError("close session callback is not configured")
        await self._close_session_callback(operation.target_session_id, operation.force)

    async def handle_user_interaction_respond(self, operation: op.UserInteractionRespondOperation) -> None:
        callback = self._respond_user_interaction_callback
        if callback is None:
            raise RuntimeError("respond user interaction callback is not configured")
        callback(operation.request_id, operation.session_id, operation.response)

    def get_active_task(self, operation_id: str) -> ActiveTask | None:
        """Return the active runtime task for an operation id if present."""

        return self.task_manager.get_by_operation(operation_id)


class Executor:
    """
    Core executor that processes operations submitted from the CLI.

    This class implements a message loop similar to Codex-rs's submission_loop,
    processing operations asynchronously and coordinating with agents.
    """

    def __init__(
        self,
        event_bus: EventBus,
        llm_clients: LLMClients,
        model_profile_provider: ModelProfileProvider | None = None,
        on_model_change: Callable[[str], None] | None = None,
    ):
        self.context = ExecutorContext(event_bus, llm_clients, model_profile_provider, on_model_change)
        self.runtime_hub = RuntimeHub(
            handle_operation=self._handle_operation,
            reject_operation=self._reject_operation,
        )
        self.context.set_close_session_callback(self.close_session)
        self.context.set_user_interaction_callbacks(
            request_callback=self.runtime_hub.request_user_interaction,
            respond_callback=self._respond_user_interaction,
            cancel_callback=self._cancel_pending_user_interactions,
        )
        self._stopped = False
        # Track completion events for all operations (not just those with ActiveTask)
        self._completion_events: dict[str, asyncio.Event] = {}
        self._background_tasks: set[asyncio.Task[None]] = set()

    async def _reject_operation(self, operation: op.Operation, active_task_id: str | None) -> None:
        session_id = getattr(operation, "session_id", None)
        if session_id is None:
            raise RuntimeError("Busy rejection requires session-bound operation")

        await self.context.emit_event(
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

    def _cancel_pending_user_interactions(self, session_id: str | None) -> bool:
        return self.runtime_hub.cancel_pending_interactions(session_id=session_id)

    def _complete_operation(self, operation: op.Operation) -> None:
        event = self._completion_events.get(operation.id)
        if event is not None:
            event.set()
        self.runtime_hub.mark_operation_completed(operation.id)

    async def submit(self, operation: op.Operation) -> str:
        """
        Submit an operation to the executor for processing.

        Args:
            operation: Operation to submit

        Returns:
            Unique operation ID for tracking
        """

        if self._stopped:
            raise RuntimeError("Executor is stopped")

        if operation.id in self._completion_events:
            raise RuntimeError(f"Operation already registered: {operation.id}")

        # Create completion event before queueing to avoid races.
        self._completion_events[operation.id] = asyncio.Event()

        await self.runtime_hub.submit(operation)

        log_debug(
            f"Submitted operation {operation.type} with ID {operation.id}",
            style="blue",
            debug_type=DebugType.EXECUTION,
        )

        return operation.id

    async def wait_next_interaction_request(self) -> PendingUserInteractionRequest:
        return await self.runtime_hub.wait_next_request()

    def has_running_tasks(self) -> bool:
        return any(not active.task.done() for active in self.context.task_manager.values())

    async def close_session(self, session_id: str, force: bool = False) -> bool:
        closed = await self.runtime_hub.close_session(session_id, force=force)
        if closed:
            self.context.drop_session_state(session_id)
        return closed

    async def reclaim_idle_sessions(self, *, idle_for_seconds: float) -> list[str]:
        reclaimed = await self.runtime_hub.reclaim_idle_runtimes(idle_for_seconds=idle_for_seconds)
        for session_id in reclaimed:
            self.context.drop_session_state(session_id)
        return reclaimed

    async def wait_for(self, operation_id: str) -> None:
        """Wait for a specific operation to complete."""
        event = self._completion_events.get(operation_id)
        if event is not None:
            await event.wait()
            self._completion_events.pop(operation_id, None)

    async def submit_and_wait(self, operation: op.Operation) -> None:
        """Submit an operation and wait for it to complete."""
        operation_id = await self.submit(operation)
        await self.wait_for(operation_id)

    async def stop(self) -> None:
        """Stop the executor and clean up resources."""
        self._stopped = True
        self.context.cancel_pending_user_interactions(session_id=None)

        # Cancel all active tasks and collect them for awaiting
        tasks_to_await: list[asyncio.Task[None]] = []
        for active in self.context.task_manager.values():
            task = active.task
            if not task.done():
                task.cancel()
                tasks_to_await.append(task)

        # Wait for all cancelled tasks to complete
        if tasks_to_await:
            await asyncio.gather(*tasks_to_await, return_exceptions=True)

        if self._background_tasks:
            await asyncio.gather(*self._background_tasks, return_exceptions=True)
            self._background_tasks.clear()

        await self.runtime_hub.stop()

        # Clear the active task manager
        self.context.task_manager.clear()

        for event in self._completion_events.values():
            event.set()

        log_debug("Executor stopped", style="yellow", debug_type=DebugType.EXECUTION)

    async def _handle_operation(self, operation: op.Operation) -> None:
        """
        Handle a single submission by executing its operation.

        This method delegates to the operation's execute method, which
        can access shared resources through the executor context.
        """
        try:
            log_debug(
                f"Handling operation {operation.id} of type {operation.type.value}",
                style="cyan",
                debug_type=DebugType.EXECUTION,
            )

            # Execute to spawn the agent task in context
            await operation.execute(handler=self.context)
            self._on_operation_applied(operation)

            active_task = self.context.get_active_task(operation.id)

            async def _await_agent_and_complete(captured_task: asyncio.Task[None]) -> None:
                try:
                    await captured_task
                finally:
                    self._complete_operation(operation)

            if active_task is None:
                self._complete_operation(operation)
            else:
                self.runtime_hub.bind_root_task(operation_id=operation.id, task_id=active_task.task_id)
                # Run in background so the submission loop can continue (e.g., to handle interrupts)
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
            await self.context.emit_event(
                events.ErrorEvent(
                    error_message=f"Operation failed: {e!s}",
                    can_retry=False,
                    session_id=session_id or "__app__",
                )
            )
            # Set completion event even on error to prevent wait_for_completion from hanging
            self._complete_operation(operation)


# Static type check: ExecutorContext must satisfy OperationHandler protocol.
# If this line causes a type error, ExecutorContext is missing required methods.
_: type[OperationHandler] = ExecutorContext
