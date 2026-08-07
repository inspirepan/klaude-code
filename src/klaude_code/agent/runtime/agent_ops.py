"""Agent lifecycle, task execution, and session management operations."""

from __future__ import annotations

import asyncio
import contextlib
import traceback
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from klaude_code.agent.agent import Agent
from klaude_code.agent.agent_profile import ModelProfileProvider
from klaude_code.agent.attachments.memory import get_existing_memory_paths_by_location
from klaude_code.agent.attachments.state import reset_attachment_loaded_flags
from klaude_code.agent.away_summary import generate_away_summary
from klaude_code.agent.bash_mode import run_bash_command
from klaude_code.agent.compaction import CompactionReason, run_compaction
from klaude_code.agent.model_fallback import build_fallback_model_config_warn, fallback_llm_client
from klaude_code.agent.prompt_suggestion import run_prompt_suggestion, should_suggest
from klaude_code.agent.runtime.llm import (
    LLMClients,
    build_llm_clients,
    clone_llm_clients,
    create_llm_client_for_candidates,
)
from klaude_code.agent.runtime.sub_agent import SubAgentLauncher
from klaude_code.agent.session_title import generate_session_title
from klaude_code.agent.side_question import run_side_question
from klaude_code.agent.skill_inventory import (
    get_skill_names_by_location,
    get_skill_warnings_by_location,
)
from klaude_code.config import format_model_preference, load_config
from klaude_code.control.event_bus import event_publish_context
from klaude_code.control.runtime.actor import SessionActor
from klaude_code.control.user_interaction import PendingUserInteractionRequest
from klaude_code.llm.client import LLMClientABC
from klaude_code.llm.image import freeze_image_for_history
from klaude_code.log import DebugType, log_debug
from klaude_code.protocol import events, message, op, user_interaction
from klaude_code.protocol.models import SubAgentState, TaskMetadata
from klaude_code.protocol.sub_agent import SubAgentResult
from klaude_code.session.session import Session
from klaude_code.update import get_startup_update_summary


def _has_summary_since_last_user_turn(session: Session) -> bool:
    """Return True if an AwaySummaryEntry appears before the most recent
    UserMessage (ignoring bash-mode user entries) in the session history.
    Used to dedup repeated recaps when no new user turn has occurred.
    """
    for item in reversed(session.conversation_history):
        if isinstance(item, message.UserMessage) and item.source != "bash_mode":
            return False
        if isinstance(item, message.AwaySummaryEntry):
            return True
    return False


@dataclass
class _PendingSideQuestion:
    """An in-flight `/btw` answer, tracked outside the session's task handles."""

    session_id: str
    task: asyncio.Task[None]


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
        self._sub_agent_launcher: SubAgentLauncher | None = None
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
        self._prompt_suggestion_tasks: dict[str, asyncio.Task[None]] = {}
        self._auto_away_summary_tasks: dict[str, asyncio.Task[None]] = {}
        self._side_question_tasks: dict[str, _PendingSideQuestion] = {}

    def set_sub_agent_launcher(self, launcher: SubAgentLauncher) -> None:
        self._sub_agent_launcher = launcher

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

    def _build_default_llm_clients(self) -> LLMClients:
        """Build a session's default clients from the current config.

        The startup template pins whatever the config held when the server
        booted, so reusing it would keep /model, /sub-agent-model and provider
        changes out of every session created afterwards until the server
        re-execs. The template stays as a fallback for a config that no longer
        resolves (e.g. the model a provider toggle just made unavailable).
        """
        try:
            return build_llm_clients(load_config())
        except Exception as exc:
            log_debug(
                f"Falling back to the startup LLM clients: {exc}",
                debug_type=DebugType.LLM_CONFIG,
            )
            return clone_llm_clients(self._llm_clients_template)

    def _ensure_session_llm_clients(self, session: Session) -> LLMClients:
        runtime = self._ensure_session_actor(session.id)
        existing = runtime.get_llm_clients()
        if existing is not None:
            return existing

        clients = self._build_default_llm_clients()
        config = load_config()

        model_config_name = session.model_config_name
        if model_config_name is not None:
            with contextlib.suppress(ValueError):
                candidates = config.iter_model_config_candidates_with_preference_fallback(
                    model_config_name,
                    config.main_model,
                )
                if candidates:
                    clients.main = create_llm_client_for_candidates(candidates)
                    clients.main_model_alias = (
                        format_model_preference([candidate.selector for candidate in candidates]) or model_config_name
                    )

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
        self._cancel_side_questions(None)
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

    async def ensure_agent(
        self,
        session_id: str | None = None,
        *,
        work_dir: Path | None = None,
        defer_welcome_context: bool = False,
        defer_replay: bool = False,
        suppress_welcome: bool = False,
    ) -> Agent:
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

        if session_id is None:
            session = Session.create(work_dir=work_dir)
        else:
            # A full history parse of a long session takes seconds; run on
            # the server's only event loop it froze event forwarding and
            # every attached client (the "first turn blocks ~4s" incident).
            session = await asyncio.to_thread(Session.load, session_id, work_dir=work_dir)

        runtime = self._ensure_session_actor(session.id)
        existing = runtime.get_agent()
        if existing is not None:
            return existing

        session_clients = self._ensure_session_llm_clients(session)

        # Top-level sessions created via `klaude run --agent TYPE` carry the
        # agent type in meta; build the matching profile (prompt + tool set).
        profile_agent_type: str | None = None
        if session.agent_type is not None and session.agent_type != "main":
            profile_agent_type = session.agent_type
        # Vanilla is a per-session flag now that the server owns all sessions.
        profile_provider: ModelProfileProvider = self._model_profile_provider
        if session.vanilla:
            from klaude_code.agent.agent_profile import VanillaModelProfileProvider

            profile_provider = VanillaModelProfileProvider()
        # System-prompt assembly scans skills and memory files on disk;
        # keep it off the server's event loop.
        profile = await asyncio.to_thread(
            profile_provider.build_profile,
            session_clients.main,
            profile_agent_type,
            work_dir=session.work_dir,
        )
        agent = Agent(
            session=session,
            profile=profile,
            compact_llm_client=session_clients.compact,
            request_user_interaction=self._build_request_user_interaction_callback(session_id=session.id),
            model_profile_provider=profile_provider,
        )

        if not suppress_welcome:
            startup_update = get_startup_update_summary()

            await self._emit_event(
                events.WelcomeEvent(
                    session_id=session.id,
                    work_dir=str(session.work_dir),
                    llm_config=session_clients.main.get_llm_config(),
                    title=session.title,
                    loaded_skills={} if defer_welcome_context else get_skill_names_by_location(),
                    loaded_skill_warnings={} if defer_welcome_context else get_skill_warnings_by_location(),
                    loaded_memories=(
                        {}
                        if defer_welcome_context
                        else get_existing_memory_paths_by_location(work_dir=session.work_dir)
                    ),
                    startup_info=events.WelcomeStartupInfo(
                        update_info=(
                            events.WelcomeUpdateInfo(
                                message=startup_update.message,
                                level=startup_update.level,
                            )
                            if startup_update is not None
                            else None
                        )
                    ),
                )
            )

        if defer_replay:
            runtime.set_agent(agent)
            if self._primary_session_id is None:
                self._primary_session_id = session.id
        else:
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

    async def init_sub_agent_session(self, session: Session) -> Agent:
        """Register a prepared sub-agent session on its own actor.

        Mirrors ``ensure_agent`` without the welcome event, history replay,
        or primary-session bookkeeping: the child renders inside the parent's
        transcript, so none of those apply.
        """
        runtime = self._ensure_session_actor(session.id)
        existing = runtime.get_agent()
        if existing is not None:
            return existing

        session_clients = self._ensure_session_llm_clients(session)
        profile_agent_type: str | None = None
        if session.agent_type is not None and session.agent_type != "main":
            profile_agent_type = session.agent_type
        profile_provider: ModelProfileProvider = self._model_profile_provider
        if session.vanilla:
            from klaude_code.agent.agent_profile import VanillaModelProfileProvider

            profile_provider = VanillaModelProfileProvider()
        # Every sub-agent spawn rebuilds a profile (skills/memory disk scan);
        # on the loop it froze all clients for the duration of each spawn.
        profile = await asyncio.to_thread(
            profile_provider.build_profile,
            session_clients.main,
            profile_agent_type,
            work_dir=session.work_dir,
        )
        session.model_name = session_clients.main.model_name
        agent = Agent(
            session=session,
            profile=profile,
            compact_llm_client=session_clients.compact,
            request_user_interaction=self._build_request_user_interaction_callback(session_id=session.id),
            model_profile_provider=profile_provider,
        )
        runtime.set_agent(agent)
        return agent

    async def init_agent(
        self,
        session_id: str,
        *,
        work_dir: Path,
        defer_welcome_context: bool = False,
        defer_replay: bool = False,
        suppress_welcome: bool = False,
    ) -> None:
        agent = await self.ensure_agent(
            session_id,
            work_dir=work_dir,
            defer_welcome_context=defer_welcome_context,
            defer_replay=defer_replay,
            suppress_welcome=suppress_welcome,
        )
        if not suppress_welcome:
            # Rehydrating a reclaimed actor is not a session switch: it must
            # not steal the primary-session slot from an interactive TUI.
            self._primary_session_id = agent.session.id

    async def replay_session_history(self, session_id: str) -> None:
        runtime = self._get_session_actor(session_id)
        agent = runtime.get_agent() if runtime is not None else None
        if agent is None:
            raise ValueError(f"Session is not initialized: {session_id}")
        async for evt in agent.replay_history():
            await self._emit_event(evt)

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
            log_debug(f"[SessionTitle] generation failed: {exc!s}", debug_type=DebugType.EXECUTION)
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
        # Sub-agent sessions render inside the parent transcript; skip the
        # per-spawn title LLM call.
        if session.parent_session_id is not None:
            return
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

    def _cancel_prompt_suggestion(self, session_id: str) -> None:
        task = self._prompt_suggestion_tasks.pop(session_id, None)
        if task is not None and not task.done():
            log_debug(
                f"[PromptSuggestion] cancel pending session={session_id}",
                debug_type=DebugType.EXECUTION,
            )
            task.cancel()

    def _cancel_auto_away_summary(self, session_id: str) -> None:
        task = self._auto_away_summary_tasks.pop(session_id, None)
        if task is None or task.done():
            return
        log_debug(
            f"[AwaySummary] cancel stale auto task session={session_id}",
            debug_type=DebugType.EXECUTION,
        )
        task.cancel()

    def cancel_auto_away_summary(self, session_id: str) -> None:
        self._cancel_auto_away_summary(session_id)

    def _schedule_prompt_suggestion(self, agent: Agent) -> None:
        """Fire-and-forget a cache-shared fork to predict the user's next prompt.

        Runs only after a task finishes cleanly (no error/abort). The result is
        persisted as a PromptSuggestionEntry in the session and emitted as a
        PromptSuggestionReadyEvent so the TUI can pre-fill the input placeholder.
        A new turn cancels any pending generation via ``_cancel_prompt_suggestion``.
        """
        session_id = agent.session.id
        # Sub-agent sessions don't surface a prompt to the user; the leader
        # session is the only one that benefits from a suggestion.
        if agent.session.sub_agent_state is not None or agent.session.parent_session_id is not None:
            return
        if agent.follow_up_count() > 0:
            log_debug(
                f"[PromptSuggestion] skip session={session_id} reason=follow-up queue pending",
                debug_type=DebugType.EXECUTION,
            )
            return
        suppress = should_suggest(agent.session)
        if suppress is not None:
            log_debug(
                f"[PromptSuggestion] skip session={session_id} reason={suppress}",
                debug_type=DebugType.EXECUTION,
            )
            return

        log_debug(
            f"[PromptSuggestion] schedule session={session_id}",
            debug_type=DebugType.EXECUTION,
        )
        self._cancel_prompt_suggestion(session_id)
        task = asyncio.create_task(self._generate_prompt_suggestion(agent))
        self._prompt_suggestion_tasks[session_id] = task

        def _cleanup(completed: asyncio.Task[None]) -> None:
            if self._prompt_suggestion_tasks.get(session_id) is completed:
                self._prompt_suggestion_tasks.pop(session_id, None)
            with contextlib.suppress(asyncio.CancelledError, Exception):
                _ = completed.exception()

        task.add_done_callback(_cleanup)

    async def _generate_prompt_suggestion(self, agent: Agent) -> None:
        session = agent.session
        try:
            result = await run_prompt_suggestion(
                session=session,
                main_profile=agent.profile,
            )
        except asyncio.CancelledError:
            log_debug(
                f"[PromptSuggestion] cancelled session={session.id}",
                debug_type=DebugType.EXECUTION,
            )
            raise
        except Exception as exc:
            log_debug(
                f"[PromptSuggestion] generation failed session={session.id}: {exc}",
                debug_type=DebugType.EXECUTION,
            )
            return
        if result is None:
            log_debug(
                f"[PromptSuggestion] no suggestion session={session.id} (generation failed before a response was produced)",
                debug_type=DebugType.EXECUTION,
            )
            return
        if result.suggestion is None:
            log_debug(
                f"[PromptSuggestion] no suggestion session={session.id} reason={result.drop_reason} raw={result.raw!r}",
                debug_type=DebugType.EXECUTION,
            )
            return
        suggestion = result.suggestion
        log_debug(
            f"[PromptSuggestion] ready session={session.id}",
            suggestion,
            debug_type=DebugType.EXECUTION,
        )
        entry = message.PromptSuggestionEntry(text=suggestion)
        session.append_history([entry])
        await self._emit_event(
            events.PromptSuggestionReadyEvent(session_id=session.id, text=suggestion),
        )

    async def _freeze_user_input_for_history(
        self,
        user_input: message.UserInputPayload,
        *,
        images_dir: Path,
    ) -> message.UserInputPayload:
        images = user_input.images
        if not images:
            return user_input
        # Freezing compresses each pasted image (~1s of CPU per multi-MB
        # screenshot); run off the event loop so submit doesn't stall the TUI.
        frozen_images = await asyncio.to_thread(
            lambda: [freeze_image_for_history(image, images_dir=images_dir) for image in images]
        )
        return message.UserInputPayload(
            text=user_input.text,
            images=frozen_images,
        )

    async def run_agent(self, operation: op.RunAgentOperation) -> None:
        agent = await self.ensure_agent(operation.session_id)
        # New user turn invalidates any pending suggestion for this session.
        self._cancel_prompt_suggestion(operation.session_id)
        self._cancel_auto_away_summary(operation.session_id)
        await self._emit_event(events.PromptSuggestionClearedEvent(session_id=operation.session_id))
        user_message_exists = any(
            isinstance(item, message.UserMessage) and item.id == operation.id
            for item in agent.session.conversation_history
        )
        frozen_input = operation.input
        if not user_message_exists:
            frozen_input = await self._freeze_user_input_for_history(
                operation.input,
                images_dir=Session.paths(agent.session.work_dir).images_dir(agent.session.id),
            )
            agent.session.append_history(
                [
                    message.UserMessage(
                        id=operation.id,
                        parts=message.parts_from_text_and_images(
                            frozen_input.text,
                            frozen_input.images,
                        ),
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
                await self._run_agent_task(agent, frozen_input, task_id, operation.session_id)

        task: asyncio.Task[None] = asyncio.create_task(_run_with_event_context())
        self._register_task(
            operation_id=operation.id,
            task_id=task_id,
            task=task,
            session_id=operation.session_id,
        )

    async def follow_up_agent(self, operation: op.FollowUpAgentOperation) -> None:
        agent = await self.ensure_agent(operation.session_id)
        agent.follow_up(operation.input)

    async def run_bash(self, operation: op.RunBashOperation) -> None:
        self._cancel_auto_away_summary(operation.session_id)
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
        self._cancel_auto_away_summary(operation.session_id)
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
        self._cancel_auto_away_summary(operation.session_id)
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

    async def generate_away_summary(self, operation: op.GenerateAwaySummaryOperation) -> None:
        """Produce a 'while you were away' recap and emit AwaySummaryEvent.

        Dedup: skip if a recap was already appended since the last user turn —
        avoids back-to-back recaps when blur/focus cycles repeat or when
        /recap is run multiple times without new user input.

        Skipped silently when the session is missing or has no content yet.
        Uses the session's fast LLM client; runs non-streaming.
        """
        agent = await self.ensure_agent(operation.session_id)

        if _has_summary_since_last_user_turn(agent.session):
            log_debug(
                f"[AwaySummary] skip (dedup, source={operation.source})",
                debug_type=DebugType.EXECUTION,
            )
            return

        user_messages_snapshot = tuple(agent.session.user_messages)

        async def _runner() -> None:
            await self._run_away_summary_task(operation, user_messages_snapshot=user_messages_snapshot)

        await self.run_background_operation(
            operation_id=operation.id,
            session_id=operation.session_id,
            runner=_runner,
        )

        if operation.source == "auto":
            active = self.get_active_task(operation.id)
            if active is not None:
                self._auto_away_summary_tasks[operation.session_id] = active.task

                def _cleanup(completed: asyncio.Task[None]) -> None:
                    if self._auto_away_summary_tasks.get(operation.session_id) is completed:
                        self._auto_away_summary_tasks.pop(operation.session_id, None)

                active.task.add_done_callback(_cleanup)

    async def _run_away_summary_task(
        self,
        operation: op.GenerateAwaySummaryOperation,
        *,
        user_messages_snapshot: tuple[str, ...],
    ) -> None:
        agent = await self.ensure_agent(operation.session_id)
        clients = self.get_session_llm_clients(operation.session_id)
        fast_client = clients.get_fast_client()

        show_spinner = operation.source == "manual"
        if show_spinner:
            await self._emit_event(events.AwaySummaryStartEvent(session_id=agent.session.id))
        try:
            text = await generate_away_summary(llm_client=fast_client, session=agent.session)
            if not text:
                log_debug(
                    f"[AwaySummary] skip (empty result, source={operation.source})",
                    debug_type=DebugType.EXECUTION,
                )
                return

            if operation.source == "auto" and tuple(agent.session.user_messages) != user_messages_snapshot:
                log_debug(
                    f"[AwaySummary] skip (stale auto result, source={operation.source})",
                    debug_type=DebugType.EXECUTION,
                )
                return
            if _has_summary_since_last_user_turn(agent.session):
                log_debug(
                    f"[AwaySummary] skip (dedup after generation, source={operation.source})",
                    debug_type=DebugType.EXECUTION,
                )
                return

            entry = message.AwaySummaryEntry(text=text, source=operation.source)
            agent.session.append_history([entry])
            await self._emit_event(
                events.AwaySummaryEvent(session_id=agent.session.id, text=text),
            )
        finally:
            if show_spinner:
                await self._emit_event(events.AwaySummaryEndEvent(session_id=agent.session.id))

    async def ask_side_question(self, operation: op.AskSideQuestionOperation) -> None:
        """Answer a `/btw` side question beside whatever the session is doing.

        The answer runs in a bare asyncio task rather than a registered runtime
        task on purpose: a side question must not make the session look busy
        (which would reject the next root operation) and must not be cancelled
        by the Esc interrupt that stops the main task.
        """
        question = operation.question.strip()
        if not question:
            # Guard here, not only in the TUI: any frontend can submit this op.
            await self._emit_event(
                events.NoticeEvent(
                    session_id=operation.session_id,
                    content="/btw needs a question, e.g. `/btw why is this cached?`",
                    is_error=True,
                )
            )
            return

        agent = await self.ensure_agent(operation.session_id)
        request_id = operation.id
        await self._emit_event(
            events.SideQuestionStartEvent(
                session_id=agent.session.id,
                request_id=request_id,
                question=question,
            )
        )
        task = asyncio.create_task(self._run_side_question(agent, question=question, request_id=request_id))
        self._side_question_tasks[request_id] = _PendingSideQuestion(session_id=agent.session.id, task=task)

        def _cleanup(completed: asyncio.Task[None]) -> None:
            pending = self._side_question_tasks.get(request_id)
            if pending is not None and pending.task is completed:
                self._side_question_tasks.pop(request_id, None)
            with contextlib.suppress(asyncio.CancelledError, Exception):
                _ = completed.exception()

        task.add_done_callback(_cleanup)

    async def _run_side_question(self, agent: Agent, *, question: str, request_id: str) -> None:
        session = agent.session
        try:
            result = await run_side_question(session=session, main_profile=agent.profile, question=question)
        except asyncio.CancelledError:
            # The session was cleared or the runtime is shutting down; whatever
            # owns the pending indicator is going away with it.
            raise
        except Exception as exc:
            log_debug(f"[SideQuestion] failed session={session.id}: {exc}", debug_type=DebugType.EXECUTION)
            await self._emit_event(
                events.SideQuestionFailedEvent(
                    session_id=session.id,
                    request_id=request_id,
                    question=question,
                    error=str(exc) or exc.__class__.__name__,
                )
            )
            return

        session.append_history(
            [
                message.SideQuestionEntry(
                    question=question,
                    answer=result.answer,
                    cache_hit_rate=result.cache_hit_rate,
                )
            ]
        )
        await self._emit_event(
            events.SideQuestionEvent(
                session_id=session.id,
                request_id=request_id,
                question=question,
                answer=result.answer,
                cache_hit_rate=result.cache_hit_rate,
            )
        )

    def cancel_side_questions(self, session_id: str) -> None:
        """Drop a session's pending answers. Called when the session goes away.

        A side question keeps no runtime task, so closing or clearing a session
        would otherwise leave one writing history for a session nobody owns.
        """
        self._cancel_side_questions(session_id)

    def _cancel_side_questions(self, session_id: str | None) -> None:
        for request_id, pending in list(self._side_question_tasks.items()):
            if session_id is not None and pending.session_id != session_id:
                continue
            self._side_question_tasks.pop(request_id, None)
            if not pending.task.done():
                log_debug(
                    f"[SideQuestion] cancel pending session={pending.session_id}",
                    debug_type=DebugType.EXECUTION,
                )
                pending.task.cancel()

    async def clear_session(self, session_id: str) -> None:
        agent = await self.ensure_agent(session_id)
        old_session_id = agent.session.id
        self._cancel_prompt_suggestion(old_session_id)
        self._cancel_auto_away_summary(old_session_id)
        self._cancel_side_questions(old_session_id)
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
            model_profile_provider=self._model_profile_provider,
        )

        old_runtime.clear_execution_state()
        new_runtime = self._ensure_session_actor(new_session.id)
        new_runtime.set_llm_clients(session_clients)
        new_runtime.set_agent(new_agent)
        if self._primary_session_id == old_session_id:
            self._primary_session_id = new_session.id

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
                loaded_skills=get_skill_names_by_location(),
                loaded_skill_warnings=get_skill_warnings_by_location(),
                loaded_memories=get_existing_memory_paths_by_location(work_dir=new_agent.session.work_dir),
            )
        )

    async def fork_and_switch_session(
        self, session_id: str, new_session_id: str, original_session_short_id: str
    ) -> None:
        """Switch the active session to an already-forked session and replay its history."""
        agent = await self.ensure_agent(session_id)
        old_session_id = agent.session.id
        self._cancel_auto_away_summary(old_session_id)
        self._cancel_side_questions(old_session_id)
        old_runtime = self._get_session_actor(old_session_id)
        if old_runtime is None:
            raise RuntimeError(f"Missing runtime for session {old_session_id}")
        session_clients = self.get_session_llm_clients(old_session_id)

        new_session = Session.load(new_session_id, work_dir=agent.session.work_dir)

        new_agent = Agent(
            session=new_session,
            profile=self._model_profile_provider.build_profile(session_clients.main, work_dir=new_session.work_dir),
            compact_llm_client=session_clients.compact,
            request_user_interaction=self._build_request_user_interaction_callback(session_id=new_session.id),
            model_profile_provider=self._model_profile_provider,
        )

        old_runtime.clear_execution_state()
        new_runtime = self._ensure_session_actor(new_session.id)
        new_runtime.set_llm_clients(session_clients)
        new_runtime.set_agent(new_agent)
        if self._primary_session_id == old_session_id:
            self._primary_session_id = new_session.id

        await self._emit_event(
            events.WelcomeEvent(
                session_id=new_agent.session.id,
                work_dir=str(new_agent.session.work_dir),
                llm_config=session_clients.main.get_llm_config(),
                title=new_agent.session.title,
                loaded_skills=get_skill_names_by_location(),
                loaded_skill_warnings=get_skill_warnings_by_location(),
                loaded_memories=get_existing_memory_paths_by_location(work_dir=new_agent.session.work_dir),
            )
        )

        async for evt in new_agent.replay_history():
            await self._emit_event(evt)

        await self._emit_event(
            events.NoticeEvent(
                session_id=new_agent.session.id,
                content=f"Forked session active. To switch back: `klaude -r {original_session_short_id}`",
                style="fork.notice",
            )
        )

    async def interrupt(
        self,
        session_id: str,
        *,
        expected_operation_id: str | None = None,
        retract_unanswered_input: bool = False,
        resume_follow_ups: bool = False,
    ) -> bool:
        runtime = self._get_session_actor(session_id)
        if runtime is None:
            return False
        if expected_operation_id is not None:
            active_root = runtime.snapshot().active_root_task
            if active_root is None or active_root.operation_id != expected_operation_id:
                log_debug(
                    f"Ignoring stale interrupt for {session_id}: "
                    f"expected operation {expected_operation_id}, "
                    f"active operation {active_root.operation_id if active_root is not None else None}",
                    debug_type=DebugType.EXECUTION,
                )
                return False
        agent = runtime.get_agent()
        show_notice = True
        retracted_text: str | None = None
        if agent is not None:
            for evt in agent.on_interrupt():
                await self._emit_event(evt)
            show_notice = agent.last_interrupt_show_notice
            if retract_unanswered_input:
                retracted_text = agent.retract_interrupted_user_message()

        await self._emit_event(
            events.InterruptEvent(session_id=session_id, show_notice=show_notice, resume_follow_ups=resume_follow_ups)
        )
        if retracted_text is not None:
            # After InterruptEvent so the display's tape filter can hide the
            # whole turn (user message through interrupt) in one contiguous span.
            await self._emit_event(events.UserMessageRetractedEvent(session_id=session_id, content=retracted_text))

        tasks_to_cancel = self._cancel_tasks_for_sessions({session_id})

        log_debug(
            f"Interrupting {len(tasks_to_cancel)} task(s) for: {session_id}",
            debug_type=DebugType.EXECUTION,
        )

        for _task_id, task in tasks_to_cancel:
            task.cancel()
        pending_tasks = [task for _task_id, task in tasks_to_cancel if not task.done()]
        if not pending_tasks:
            return True
        try:
            _ = await asyncio.wait_for(
                asyncio.gather(*pending_tasks, return_exceptions=True),
                timeout=2.0,
            )
        except TimeoutError:
            log_debug(
                f"Interrupt timeout while waiting task cancellation for: {session_id}",
                debug_type=DebugType.EXECUTION,
            )
        return True

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
                state: SubAgentState,
                record_session_id: Callable[[str], None] | None,
                register_metadata_getter: Callable[[Callable[[], TaskMetadata | None]], None] | None,
                register_progress_getter: Callable[[Callable[[], str | None]], None] | None,
            ) -> SubAgentResult:
                if agent.session.sub_agent_state is not None or agent.session.parent_session_id is not None:
                    raise RuntimeError("Sub-agents cannot spawn nested sub-agents")
                launcher = self._sub_agent_launcher
                if launcher is None:
                    raise RuntimeError("Sub-agent launcher is not wired")
                child_task_id = uuid4().hex
                self._on_child_task_state_change(session_id, child_task_id, True)
                try:
                    return await launcher.run_sub_agent(
                        agent,
                        state,
                        record_session_id=record_session_id,
                        register_metadata_getter=register_metadata_getter,
                        register_progress_getter=register_progress_getter,
                    )
                finally:
                    self._on_child_task_state_change(session_id, child_task_id, False)

            async for event in agent.run_task(user_input, run_subtask=_runner):
                await self._emit_event(event)

            # Task completed normally — predict the user's next prompt in the
            # background. Cancelled implicitly when the next user turn starts.
            self._schedule_prompt_suggestion(agent)

        except asyncio.CancelledError:
            log_debug(
                f"Agent task {task_id} was cancelled",
                debug_type=DebugType.EXECUTION,
            )
            await self._emit_event(events.TaskFinishEvent(session_id=session_id, task_result="task cancelled"))

        except Exception as e:
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
            session_clients = self.get_session_llm_clients(session_id)
            while True:
                compact_client = session_clients.get_compact_client()
                try:
                    result = await run_compaction(
                        session=agent.session,
                        reason=CompactionReason(reason),
                        focus=operation.focus,
                        llm_client=compact_client,
                        llm_config=compact_client.get_llm_config(),
                        cancel=cancel_event,
                        main_profile=agent.profile,
                    )
                    break
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    fallback = fallback_llm_client(compact_client, str(exc))
                    if fallback is None:
                        raise
                    entry, fallback_event = build_fallback_model_config_warn(
                        session_id=session_id,
                        fallback=fallback,
                        error_message=str(exc),
                    )
                    agent.session.append_history([entry])
                    if session_clients.compact is None and compact_client is session_clients.main:
                        agent.set_model_profile(
                            self._model_profile_provider.build_profile(compact_client, work_dir=agent.session.work_dir)
                        )
                    await self._emit_event(fallback_event)
            log_debug(f"[Compact:{reason}] result", str(result.to_entry()), debug_type=DebugType.RESPONSE)
            reset_attachment_loaded_flags(agent.session.file_tracker)
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
            if result.fork_event is not None:
                await self._emit_event(result.fork_event)
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
