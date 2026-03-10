"""Agent lifecycle, task execution, and session management operations."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from klaude_code.config import load_config
from klaude_code.core.agent.agent import Agent
from klaude_code.core.agent.runtime_llm import LLMClients, clone_llm_clients
from klaude_code.core.agent.runtime_sub_agent import SubAgentExecutor
from klaude_code.core.agent.session_title import generate_session_title
from klaude_code.core.agent_profile import ModelProfileProvider
from klaude_code.core.bash_mode import run_bash_command
from klaude_code.core.compaction import CompactionReason, run_compaction
from klaude_code.core.control.event_bus import event_publish_context
from klaude_code.core.control.session_actor import SessionActor
from klaude_code.core.control.user_interaction import PendingUserInteractionRequest
from klaude_code.core.loaded_skills import (
    get_loaded_skill_names_by_location,
    get_loaded_skill_warnings_by_location,
)
from klaude_code.core.memory import get_existing_memory_paths_by_location
from klaude_code.llm.client import LLMClientABC
from klaude_code.llm.registry import create_llm_client
from klaude_code.log import DebugType, log_debug
from klaude_code.protocol import events, message, model, op, user_interaction
from klaude_code.protocol.sub_agent import SubAgentResult
from klaude_code.session.session import Session


@dataclass
class ActiveTask:
    """Track an in-flight runtime task."""

    task_id: str
    operation_id: str
    task: asyncio.Task[None]
    session_id: str


class AgentOperationHandler:
    """Coordinate agent lifecycle and in-flight tasks for operation execution."""

    def __init__(
        self,
        *,
        emit_event: Callable[[events.Event], Awaitable[None]],
        llm_clients: LLMClients,
        model_profile_provider: ModelProfileProvider,
        sub_agent_manager: SubAgentExecutor,
        on_child_task_state_change: Callable[[str, str, bool], None],
        ensure_session_actor: Callable[[str], SessionActor],
        get_session_actor: Callable[[str], SessionActor | None],
        get_session_actor_for_operation: Callable[[str], SessionActor | None],
        list_session_actors: Callable[[], list[SessionActor]],
        register_task: Callable[[str, str, str, asyncio.Task[None]], None],
        remove_task: Callable[[str, str], None],
        request_user_interaction: Callable[
            [PendingUserInteractionRequest],
            Awaitable[user_interaction.UserInteractionResponse],
        ],
    ) -> None:
        self._emit_event = emit_event
        self._llm_clients_template = llm_clients
        self._model_profile_provider = model_profile_provider
        self._sub_agent_manager = sub_agent_manager
        self._on_child_task_state_change = on_child_task_state_change
        self._ensure_session_actor = ensure_session_actor
        self._get_session_actor = get_session_actor
        self._get_session_actor_for_operation = get_session_actor_for_operation
        self._list_session_actors = list_session_actors
        self._register_runtime_task = register_task
        self._remove_runtime_task = remove_task
        self._request_user_interaction_callback = request_user_interaction
        self._primary_session_id: str | None = None
        self._title_refresh_tasks: dict[str, asyncio.Task[None]] = {}

    async def _request_user_interaction(
        self,
        session_id: str,
        request_id: str,
        source: user_interaction.UserInteractionSource,
        payload: user_interaction.UserInteractionRequestPayload,
        tool_call_id: str | None,
    ) -> user_interaction.UserInteractionResponse:
        allowed_sources: set[user_interaction.UserInteractionSource] = {
            "tool",
            "operation_model",
            "operation_thinking",
            "operation_sub_agent_model",
        }
        if source not in allowed_sources:
            raise ValueError(f"Unsupported user interaction source: {source}")
        runtime = self._get_session_actor(session_id)
        if runtime is None:
            raise RuntimeError("No active runtime session")
        agent = runtime.get_agent()
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

    def _ensure_session_llm_clients(self, session: Session) -> LLMClients:
        runtime = self._ensure_session_actor(session.id)
        existing = runtime.get_llm_clients()
        if existing is not None:
            return existing

        clients = clone_llm_clients(self._llm_clients_template)
        config = load_config()

        model_config_name = session.model_config_name
        if model_config_name is not None:
            with contextlib.suppress(ValueError):
                model_config = config.get_model_config(model_config_name)
                clients.main = create_llm_client(model_config)
                clients.main_model_alias = model_config_name

        if session.model_thinking is not None:
            clients.main.get_llm_config().thinking = session.model_thinking.model_copy(deep=True)

        runtime.set_llm_clients(clients)
        return clients

    def get_session_llm_clients(self, session_id: str) -> LLMClients:
        runtime = self._get_session_actor(session_id)
        if runtime is None:
            raise RuntimeError(f"Missing runtime for session {session_id}")
        clients = runtime.get_llm_clients()
        if clients is None:
            raise RuntimeError(f"Missing session llm clients for session {session_id}")
        return clients

    def set_session_main_client(self, *, session_id: str, client: LLMClientABC, model_alias: str) -> None:
        clients = self.get_session_llm_clients(session_id)
        clients.main = client
        clients.main_model_alias = model_alias

    def get_active_task(self, operation_id: str) -> ActiveTask | None:
        runtime = self._get_session_actor_for_operation(operation_id)
        if runtime is None:
            return None
        handle = runtime.get_active_task(operation_id)
        if handle is None:
            return None
        return ActiveTask(
            task_id=handle.task_id,
            operation_id=handle.operation_id,
            task=handle.task,
            session_id=runtime.session_id,
        )

    def list_active_tasks(self) -> list[ActiveTask]:
        active_tasks: list[ActiveTask] = []
        for runtime in self._list_session_actors():
            for handle in runtime.list_active_tasks():
                active_tasks.append(
                    ActiveTask(
                        task_id=handle.task_id,
                        operation_id=handle.operation_id,
                        task=handle.task,
                        session_id=runtime.session_id,
                    )
                )
        return active_tasks

    def clear_active_tasks(self) -> None:
        for runtime in self._list_session_actors():
            for _, task in runtime.cancel_active_tasks():
                if not task.done():
                    task.cancel()

    def _register_task(self, *, operation_id: str, task_id: str, task: asyncio.Task[None], session_id: str) -> None:
        self._register_runtime_task(session_id, operation_id, task_id, task)

    def _remove_task(self, *, session_id: str, task_id: str) -> None:
        self._remove_runtime_task(session_id, task_id)

    def _cancel_tasks_for_sessions(self, session_ids: set[str]) -> list[tuple[str, asyncio.Task[None]]]:
        tasks_to_cancel: list[tuple[str, asyncio.Task[None]]] = []
        for session_id in session_ids:
            runtime = self._get_session_actor(session_id)
            if runtime is None:
                continue
            tasks_to_cancel.extend(runtime.cancel_active_tasks())
        return tasks_to_cancel

    def current_session_id(self) -> str | None:
        session_id = self._primary_session_id
        if session_id is None:
            return None
        runtime = self._get_session_actor(session_id)
        if runtime is None or runtime.get_agent() is None:
            self._primary_session_id = None
            return None
        return session_id

    @property
    def current_agent(self) -> Agent | None:
        session_id = self.current_session_id()
        if session_id is None:
            return None
        runtime = self._get_session_actor(session_id)
        if runtime is None:
            return None
        return runtime.get_agent()

    async def ensure_agent(self, session_id: str | None = None, *, work_dir: Path | None = None) -> Agent:
        """Return the agent for a session, creating or loading as needed.

        work_dir is required when the session needs to be created or loaded from disk.
        It can be omitted when the agent is already initialized in memory.
        """

        if session_id is not None:
            runtime = self._get_session_actor(session_id)
            if runtime is not None:
                existing = runtime.get_agent()
                if existing is not None:
                    return existing

        if work_dir is None:
            raise ValueError(
                "work_dir is required to create or load a session; "
                "the agent must be initialized via InitAgentOperation first"
            )

        session = (
            Session.create(work_dir=work_dir) if session_id is None else Session.load(session_id, work_dir=work_dir)
        )

        runtime = self._ensure_session_actor(session.id)
        existing = runtime.get_agent()
        if existing is not None:
            return existing

        session_clients = self._ensure_session_llm_clients(session)

        profile = self._model_profile_provider.build_profile(session_clients.main, work_dir=session.work_dir)
        agent = Agent(
            session=session,
            profile=profile,
            compact_llm_client=session_clients.compact,
            request_user_interaction=self._build_request_user_interaction_callback(session_id=session.id),
        )

        await self._emit_event(
            events.WelcomeEvent(
                session_id=session.id,
                work_dir=str(session.work_dir),
                llm_config=session_clients.main.get_llm_config(),
                title=session.title,
                loaded_skills=get_loaded_skill_names_by_location(),
                loaded_skill_warnings=get_loaded_skill_warnings_by_location(),
                loaded_memories=get_existing_memory_paths_by_location(work_dir=session.work_dir),
            )
        )

        async for evt in agent.replay_history():
            await self._emit_event(evt)

        runtime.set_agent(agent)
        if self._primary_session_id is None:
            self._primary_session_id = session.id
        log_debug(
            f"Initialized agent for session: {session.id}",
            debug_type=DebugType.EXECUTION,
        )
        return agent

    async def init_agent(self, session_id: str, *, work_dir: Path) -> None:
        agent = await self.ensure_agent(session_id, work_dir=work_dir)
        self._primary_session_id = agent.session.id

    async def _refresh_session_title(
        self,
        session: Session,
        *,
        user_messages_snapshot: list[str],
        previous_title_snapshot: str | None,
    ) -> None:
        session_clients = self.get_session_llm_clients(session.id)
        title_client = session_clients.fast or session_clients.main
        if session_clients.fast is None:
            log_debug(
                f"[SessionTitle] fast client unavailable; falling back to main model for session {session.id}",
                debug_type=DebugType.RESPONSE,
            )

        try:
            title = await generate_session_title(
                llm_client=title_client,
                user_messages=user_messages_snapshot,
                previous_title=previous_title_snapshot,
            )
        except asyncio.CancelledError:
            return
        except Exception as exc:
            log_debug(f"Session title generation failed: {exc!s}", debug_type=DebugType.EXECUTION)
            return

        if session.user_messages != user_messages_snapshot:
            log_debug(f"[SessionTitle] stale result skipped for session {session.id}", debug_type=DebugType.RESPONSE)
            return
        if title is None:
            return
        if not session.update_title(title):
            return
        await self._emit_event(events.SessionTitleChangedEvent(session_id=session.id, title=title))

    def _schedule_session_title_refresh(self, session: Session) -> None:
        user_messages_snapshot = list(session.user_messages)
        previous_title_snapshot = session.title if len(user_messages_snapshot) > 1 else None
        existing = self._title_refresh_tasks.get(session.id)
        if existing is not None and not existing.done():
            existing.cancel()

        task = asyncio.create_task(
            self._refresh_session_title(
                session,
                user_messages_snapshot=user_messages_snapshot,
                previous_title_snapshot=previous_title_snapshot,
            )
        )
        self._title_refresh_tasks[session.id] = task

        def _cleanup(completed: asyncio.Task[None]) -> None:
            if self._title_refresh_tasks.get(session.id) is completed:
                self._title_refresh_tasks.pop(session.id, None)
            with contextlib.suppress(asyncio.CancelledError, Exception):
                _ = completed.exception()

        task.add_done_callback(_cleanup)

    def _should_refresh_session_title_during_task(self, session_id: str) -> bool:
        return self.get_session_llm_clients(session_id).fast is not None

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
        if self._should_refresh_session_title_during_task(agent.session.id):
            self._schedule_session_title_refresh(agent.session)

        existing_active = self.get_active_task(operation.id)
        if existing_active is not None and not existing_active.task.done():
            raise RuntimeError(f"Active task already registered for operation {operation.id}")

        task_id = uuid4().hex

        async def _run_with_event_context() -> None:
            with event_publish_context(task_id=task_id):
                await self._run_agent_task(agent, operation.input, task_id, operation.session_id)

        task: asyncio.Task[None] = asyncio.create_task(_run_with_event_context())
        self._register_task(
            operation_id=operation.id,
            task_id=task_id,
            task=task,
            session_id=operation.session_id,
        )

    async def run_bash(self, operation: op.RunBashOperation) -> None:
        agent = await self.ensure_agent(operation.session_id)

        existing_active = self.get_active_task(operation.id)
        if existing_active is not None and not existing_active.task.done():
            raise RuntimeError(f"Active task already registered for operation {operation.id}")

        task_id = uuid4().hex

        async def _run_with_event_context() -> None:
            with event_publish_context(task_id=task_id):
                await self._run_bash_task(
                    session=agent.session,
                    command=operation.command,
                    task_id=task_id,
                    session_id=operation.session_id,
                )

        task: asyncio.Task[None] = asyncio.create_task(_run_with_event_context())
        self._register_task(
            operation_id=operation.id,
            task_id=task_id,
            task=task,
            session_id=operation.session_id,
        )

    async def run_background_operation(
        self,
        *,
        operation_id: str,
        session_id: str,
        runner: Callable[[], Awaitable[None]],
    ) -> None:
        await self.ensure_agent(session_id)

        existing_active = self.get_active_task(operation_id)
        if existing_active is not None and not existing_active.task.done():
            raise RuntimeError(f"Active task already registered for operation {operation_id}")

        task_id = uuid4().hex

        async def _run_with_event_context() -> None:
            with event_publish_context(task_id=task_id):
                try:
                    await runner()
                finally:
                    self._remove_task(session_id=session_id, task_id=task_id)

        task: asyncio.Task[None] = asyncio.create_task(_run_with_event_context())
        self._register_task(
            operation_id=operation_id,
            task_id=task_id,
            task=task,
            session_id=session_id,
        )

    async def continue_agent(self, operation: op.ContinueAgentOperation) -> None:
        """Continue agent execution without adding a new user message."""
        agent = await self.ensure_agent(operation.session_id)

        existing_active = self.get_active_task(operation.id)
        if existing_active is not None and not existing_active.task.done():
            raise RuntimeError(f"Active task already registered for operation {operation.id}")

        # Use empty input since we're continuing from existing history
        empty_input = message.UserInputPayload(text="")
        task_id = uuid4().hex

        async def _run_with_event_context() -> None:
            with event_publish_context(task_id=task_id):
                await self._run_agent_task(agent, empty_input, task_id, operation.session_id)

        task: asyncio.Task[None] = asyncio.create_task(_run_with_event_context())
        self._register_task(
            operation_id=operation.id,
            task_id=task_id,
            task=task,
            session_id=operation.session_id,
        )

    async def compact_session(self, operation: op.CompactSessionOperation) -> None:
        agent = await self.ensure_agent(operation.session_id)

        if self._cancel_tasks_for_sessions({operation.session_id}):
            await self.interrupt(operation.session_id)

        existing_active = self.get_active_task(operation.id)
        if existing_active is not None and not existing_active.task.done():
            raise RuntimeError(f"Active task already registered for operation {operation.id}")

        task_id = uuid4().hex

        async def _run_with_event_context() -> None:
            with event_publish_context(task_id=task_id):
                await self._run_compaction_task(agent, operation, task_id, operation.session_id)

        task: asyncio.Task[None] = asyncio.create_task(_run_with_event_context())
        self._register_task(
            operation_id=operation.id,
            task_id=task_id,
            task=task,
            session_id=operation.session_id,
        )

    async def clear_session(self, session_id: str) -> None:
        agent = await self.ensure_agent(session_id)
        old_session_id = agent.session.id
        old_runtime = self._get_session_actor(old_session_id)
        if old_runtime is None:
            raise RuntimeError(f"Missing runtime for session {old_session_id}")
        session_clients = self.get_session_llm_clients(old_session_id)
        new_session = Session.create(work_dir=agent.session.work_dir)
        new_session.model_name = agent.session.model_name
        new_session.model_config_name = agent.session.model_config_name
        new_session.model_thinking = agent.session.model_thinking

        new_agent = Agent(
            session=new_session,
            profile=self._model_profile_provider.build_profile(session_clients.main, work_dir=new_session.work_dir),
            compact_llm_client=session_clients.compact,
            request_user_interaction=self._build_request_user_interaction_callback(session_id=new_session.id),
        )

        # Transfer holder from old session to new session before clearing.
        old_holder_key = old_runtime.get_holder_key()

        old_runtime.clear_execution_state()
        new_runtime = self._ensure_session_actor(new_session.id)
        new_runtime.set_llm_clients(session_clients)
        new_runtime.set_agent(new_agent)
        if self._primary_session_id == old_session_id:
            self._primary_session_id = new_session.id

        if old_holder_key is not None:
            new_runtime.try_acquire_holder(old_holder_key)

        await self._emit_event(
            events.NoticeEvent(
                session_id=new_agent.session.id,
                content="started new conversation",
            )
        )
        await self._emit_event(
            events.WelcomeEvent(
                session_id=new_agent.session.id,
                work_dir=str(new_agent.session.work_dir),
                llm_config=session_clients.main.get_llm_config(),
                title=new_agent.session.title,
                loaded_skills=get_loaded_skill_names_by_location(),
                loaded_skill_warnings=get_loaded_skill_warnings_by_location(),
                loaded_memories=get_existing_memory_paths_by_location(work_dir=new_agent.session.work_dir),
            )
        )

    async def interrupt(self, session_id: str) -> None:
        runtime = self._get_session_actor(session_id)
        if runtime is None:
            return
        agent = runtime.get_agent()
        if agent is not None:
            for evt in agent.on_interrupt():
                await self._emit_event(evt)

        await self._emit_event(events.InterruptEvent(session_id=session_id))

        tasks_to_cancel = self._cancel_tasks_for_sessions({session_id})

        scope = session_id
        log_debug(
            f"Interrupting {len(tasks_to_cancel)} task(s) for: {scope}",
            debug_type=DebugType.EXECUTION,
        )

        for _task_id, task in tasks_to_cancel:
            task.cancel()
        pending_tasks = [task for _task_id, task in tasks_to_cancel if not task.done()]
        if not pending_tasks:
            return
        try:
            _ = await asyncio.wait_for(
                asyncio.gather(*pending_tasks, return_exceptions=True),
                timeout=2.0,
            )
        except TimeoutError:
            log_debug(
                f"Interrupt timeout while waiting task cancellation for: {scope}",
                debug_type=DebugType.EXECUTION,
            )

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
                debug_type=DebugType.EXECUTION,
            )

            async def _runner(
                state: model.SubAgentState,
                record_session_id: Callable[[str], None] | None,
                register_metadata_getter: Callable[[Callable[[], model.TaskMetadata | None]], None] | None,
                register_progress_getter: Callable[[Callable[[], str | None]], None] | None,
            ) -> SubAgentResult:
                session_clients = self.get_session_llm_clients(session_id)
                child_task_id = uuid4().hex
                self._on_child_task_state_change(session_id, child_task_id, True)
                try:
                    return await self._sub_agent_manager.run_sub_agent(
                        agent,
                        state,
                        llm_clients=session_clients,
                        record_session_id=record_session_id,
                        register_metadata_getter=register_metadata_getter,
                        register_progress_getter=register_progress_getter,
                    )
                finally:
                    self._on_child_task_state_change(session_id, child_task_id, False)

            async for event in agent.run_task(user_input, run_subtask=_runner):
                await self._emit_event(event)

        except asyncio.CancelledError:
            log_debug(
                f"Agent task {task_id} was cancelled",
                debug_type=DebugType.EXECUTION,
            )
            await self._emit_event(events.TaskFinishEvent(session_id=session_id, task_result="task cancelled"))

        except Exception as e:
            import traceback

            log_debug(
                f"Agent task {task_id} failed: {e!s}",
                debug_type=DebugType.EXECUTION,
            )
            log_debug(traceback.format_exc(), debug_type=DebugType.EXECUTION)
            await self._emit_event(
                events.ErrorEvent(
                    error_message=f"Agent task failed: [{e.__class__.__name__}] {e!s} {traceback.format_exc()}",
                    can_retry=False,
                    session_id=session_id,
                )
            )
        finally:
            self._remove_task(session_id=session_id, task_id=task_id)
            if not self._should_refresh_session_title_during_task(session_id):
                self._schedule_session_title_refresh(agent.session)
            log_debug(
                f"Cleaned up agent task {task_id}",
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
            self._remove_task(session_id=session_id, task_id=task_id)

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
            compact_client = self.get_session_llm_clients(session_id).get_compact_client()
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
            self._remove_task(session_id=session_id, task_id=task_id)


class AgentRunner:
    def __init__(self, operation_handler: AgentOperationHandler) -> None:
        self._operation_handler = operation_handler

    def current_session_id(self) -> str | None:
        return self._operation_handler.current_session_id()

    @property
    def current_agent(self) -> Agent | None:
        return self._operation_handler.current_agent

    async def init_agent(self, session_id: str, *, work_dir: Path) -> None:
        await self._operation_handler.init_agent(session_id, work_dir=work_dir)

    async def run_agent(self, operation: op.RunAgentOperation) -> None:
        await self._operation_handler.run_agent(operation)

    async def continue_agent(self, operation: op.ContinueAgentOperation) -> None:
        await self._operation_handler.continue_agent(operation)

    async def compact_session(self, operation: op.CompactSessionOperation) -> None:
        await self._operation_handler.compact_session(operation)

    async def clear_session(self, session_id: str) -> None:
        await self._operation_handler.clear_session(session_id)

    async def interrupt(self, session_id: str) -> None:
        await self._operation_handler.interrupt(session_id)

    async def ensure_agent(self, session_id: str, *, work_dir: Path | None = None) -> Agent:
        return await self._operation_handler.ensure_agent(session_id, work_dir=work_dir)

    def get_session_llm_clients(self, session_id: str) -> LLMClients:
        return self._operation_handler.get_session_llm_clients(session_id)

    def set_session_main_client(self, *, session_id: str, client: LLMClientABC, model_alias: str) -> None:
        self._operation_handler.set_session_main_client(session_id=session_id, client=client, model_alias=model_alias)

    def get_active_task(self, operation_id: str) -> ActiveTask | None:
        return self._operation_handler.get_active_task(operation_id)

    def list_active_tasks(self) -> list[ActiveTask]:
        return self._operation_handler.list_active_tasks()

    async def run_background_operation(
        self,
        *,
        operation_id: str,
        session_id: str,
        runner: Callable[[], Awaitable[None]],
    ) -> None:
        await self._operation_handler.run_background_operation(
            operation_id=operation_id,
            session_id=session_id,
            runner=runner,
        )

    def clear_active_tasks(self) -> None:
        self._operation_handler.clear_active_tasks()


class BashRunner:
    def __init__(self, operation_handler: AgentOperationHandler) -> None:
        self._operation_handler = operation_handler

    async def run_bash(self, operation: op.RunBashOperation) -> None:
        await self._operation_handler.run_bash(operation)
