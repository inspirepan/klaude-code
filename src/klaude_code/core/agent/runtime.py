"""Agent execution layer and operation handlers."""

from __future__ import annotations

import asyncio
import contextlib
import json
import subprocess
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from pathlib import Path
from uuid import uuid4

from klaude_code.config import Config, load_config
from klaude_code.config.sub_agent_model_helper import SubAgentModelHelper
from klaude_code.core.agent.agent import Agent
from klaude_code.core.agent_profile import DefaultModelProfileProvider, ModelProfileProvider
from klaude_code.core.bash_mode import run_bash_command
from klaude_code.core.compaction import CompactionReason, run_compaction
from klaude_code.core.control.event_bus import EventBus
from klaude_code.core.control.user_interaction import PendingUserInteractionRequest
from klaude_code.core.loaded_skills import (
    get_loaded_skill_names_by_location,
    get_loaded_skill_warnings_by_location,
)
from klaude_code.core.memory import get_existing_memory_paths_by_location
from klaude_code.llm.client import LLMClientABC
from klaude_code.llm.registry import create_llm_client
from klaude_code.log import DebugType, log_debug
from klaude_code.protocol import commands, events, message, model, op, user_interaction
from klaude_code.protocol.llm_param import LLMConfigParameter, Thinking
from klaude_code.protocol.op_handler import OperationHandler
from klaude_code.protocol.sub_agent import SubAgentResult, get_sub_agent_profile
from klaude_code.protocol.tools import SubAgentType
from klaude_code.session.export import build_export_html, get_default_export_path
from klaude_code.session.session import Session


def _default_sub_clients() -> dict[SubAgentType, LLMClientABC]:
    return {}


@dataclass
class LLMClients:
    """Container for LLM clients used by main agent and sub-agents."""

    main: LLMClientABC
    main_model_alias: str = ""
    sub_clients: dict[SubAgentType, LLMClientABC] = dataclass_field(default_factory=_default_sub_clients)
    compact: LLMClientABC | None = None

    def get_client(self, sub_agent_type: SubAgentType | None = None) -> LLMClientABC:
        if sub_agent_type is None:
            return self.main
        client = self.sub_clients.get(sub_agent_type)
        if client is not None:
            return client
        return self.main

    def get_compact_client(self) -> LLMClientABC:
        return self.compact or self.main


def build_llm_clients(
    config: Config,
    *,
    model_override: str | None = None,
    skip_sub_agents: bool = False,
) -> LLMClients:
    model_name = model_override or config.main_model
    if model_name is None:
        raise ValueError("No model specified. Set main_model in the config or pass --model.")
    llm_config = config.get_model_config(model_name)

    log_debug(
        "Main LLM config",
        llm_config.model_dump_json(exclude_none=True),
        style="yellow",
        debug_type=DebugType.LLM_CONFIG,
    )

    main_client = create_llm_client(llm_config)

    compact_client: LLMClientABC | None = None
    if config.compact_model:
        compact_llm_config = config.get_model_config(config.compact_model)
        log_debug(
            "Compact LLM config",
            compact_llm_config.model_dump_json(exclude_none=True),
            style="yellow",
            debug_type=DebugType.LLM_CONFIG,
        )
        compact_client = create_llm_client(compact_llm_config)

    if skip_sub_agents:
        return LLMClients(main=main_client, main_model_alias=model_name, compact=compact_client)

    helper = SubAgentModelHelper(config)
    sub_agent_configs = helper.build_sub_agent_client_configs()
    user_sub_agent_models = config.get_user_sub_agent_models()

    sub_clients: dict[SubAgentType, LLMClientABC] = {}
    for sub_agent_type, sub_model_name in sub_agent_configs.items():
        try:
            sub_llm_config = config.get_model_config(sub_model_name)
            sub_clients[sub_agent_type] = create_llm_client(sub_llm_config)
        except ValueError:
            profile = get_sub_agent_profile(sub_agent_type)
            role_key = profile.invoker_type
            if role_key is not None and role_key in user_sub_agent_models:
                raise
            log_debug(
                f"Sub-agent '{sub_agent_type}' builtin model '{sub_model_name}' not available, falling back to main model",
                style="yellow",
                debug_type=DebugType.LLM_CONFIG,
            )

    return LLMClients(main=main_client, main_model_alias=model_name, sub_clients=sub_clients, compact=compact_client)


class SubAgentExecutor:
    """Run sub-agent tasks and forward their events to the UI."""

    def __init__(
        self,
        emit_event: Callable[[events.Event], Awaitable[None]],
        llm_clients: LLMClients,
        model_profile_provider: ModelProfileProvider,
    ) -> None:
        self._emit_event = emit_event
        self._llm_clients = llm_clients
        self._model_profile_provider = model_profile_provider

    async def emit_event(self, event: events.Event) -> None:
        await self._emit_event(event)

    async def run_sub_agent(
        self,
        parent_agent: Agent,
        state: model.SubAgentState,
        *,
        llm_clients: LLMClients | None = None,
        record_session_id: Callable[[str], None] | None = None,
        register_metadata_getter: Callable[[Callable[[], model.TaskMetadata | None]], None] | None = None,
        register_progress_getter: Callable[[Callable[[], str | None]], None] | None = None,
    ) -> SubAgentResult:
        parent_session = parent_agent.session
        resume_session_id = state.resume

        def _append_agent_id(task_result: str, session_id: str) -> str:
            trimmed = (task_result or "").rstrip()
            footer = f"agentId: {session_id} (for resuming to continue this agent's work if needed)"
            if trimmed.strip():
                return f"{trimmed}\n\n{footer}"
            return footer

        if resume_session_id:
            try:
                child_session = Session.load(resume_session_id)
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                return SubAgentResult(
                    task_result=f"Failed to resume sub-agent session '{resume_session_id}': {exc}",
                    session_id="",
                    error=True,
                )

            if child_session.sub_agent_state is None:
                return SubAgentResult(
                    task_result=(f"Invalid resume id '{resume_session_id}': target session is not a sub-agent session"),
                    session_id="",
                    error=True,
                )
            if child_session.sub_agent_state.sub_agent_type != state.sub_agent_type:
                return SubAgentResult(
                    task_result=(
                        "Invalid resume id: sub-agent type mismatch. "
                        f"Expected '{state.sub_agent_type}', got '{child_session.sub_agent_state.sub_agent_type}'."
                    ),
                    session_id="",
                    error=True,
                )

            if record_session_id is not None:
                record_session_id(child_session.id)

            child_session.sub_agent_state.sub_agent_desc = state.sub_agent_desc
            child_session.sub_agent_state.sub_agent_prompt = state.sub_agent_prompt
            child_session.sub_agent_state.resume = resume_session_id
            child_session.sub_agent_state.output_schema = state.output_schema
        else:
            child_session = Session(work_dir=parent_session.work_dir)
            child_session.sub_agent_state = state

            if record_session_id is not None:
                record_session_id(child_session.id)

        clients = llm_clients or self._llm_clients
        child_profile = self._model_profile_provider.build_profile(
            clients.get_client(state.sub_agent_type),
            state.sub_agent_type,
            output_schema=state.output_schema,
        )

        child_agent = Agent(session=child_session, profile=child_profile)

        log_debug(
            f"Running sub-agent {state.sub_agent_type} in session {child_session.id}",
            style="cyan",
            debug_type=DebugType.EXECUTION,
        )

        def _get_partial_metadata() -> model.TaskMetadata | None:
            metadata = child_agent.get_partial_metadata()
            if metadata is not None:
                metadata.sub_agent_name = state.sub_agent_type
                metadata.description = state.sub_agent_desc or None
            return metadata

        if register_metadata_getter is not None:
            register_metadata_getter(_get_partial_metadata)

        _ARGS_MAX_LEN = 500
        tool_call_log: dict[str, tuple[str, str]] = {}
        completed_calls: set[str] = set()

        def _get_progress() -> str | None:
            if not tool_call_log:
                return None
            lines: list[str] = []
            for call_id, (tool_name, arguments) in tool_call_log.items():
                status = "completed" if call_id in completed_calls else "interrupted"
                args_display = arguments if len(arguments) <= _ARGS_MAX_LEN else arguments[:_ARGS_MAX_LEN] + "..."
                lines.append(f"- {tool_name}({args_display}) [{status}]")
            return "\n".join(lines)

        if register_progress_getter is not None:
            register_progress_getter(_get_progress)

        try:
            result: str = ""
            task_metadata: model.TaskMetadata | None = None
            sub_agent_input = message.UserInputPayload(text=state.sub_agent_prompt, images=None)
            child_session.append_history(
                [
                    message.UserMessage(
                        parts=message.parts_from_text_and_images(sub_agent_input.text, sub_agent_input.images)
                    )
                ]
            )
            async for event in child_agent.run_task(sub_agent_input):
                if isinstance(event, events.ToolCallEvent):
                    tool_call_log[event.tool_call_id] = (event.tool_name, event.arguments)
                elif isinstance(event, events.ToolResultEvent):
                    completed_calls.add(event.tool_call_id)

                if isinstance(event, events.TaskFinishEvent):
                    result = _append_agent_id(event.task_result, child_session.id)
                    event = events.TaskFinishEvent(
                        session_id=event.session_id,
                        task_result=result,
                        has_structured_output=event.has_structured_output,
                    )
                elif isinstance(event, events.TaskMetadataEvent):
                    task_metadata = event.metadata.main_agent
                    task_metadata.sub_agent_name = state.sub_agent_type
                    task_metadata.description = state.sub_agent_desc or None
                await self.emit_event(event)

            await child_session.wait_for_flush()
            return SubAgentResult(
                task_result=result,
                session_id=child_session.id,
                task_metadata=task_metadata,
            )
        except asyncio.CancelledError:
            for evt in child_agent.on_interrupt():
                await self.emit_event(evt)

            log_debug(
                f"Sub-agent task for {state.sub_agent_type} was cancelled",
                style="yellow",
                debug_type=DebugType.EXECUTION,
            )
            raise
        except Exception as exc:  # pragma: no cover - defensive logging
            log_debug(
                f"Sub-agent task failed: [{exc.__class__.__name__}] {exc!s}",
                style="red",
                debug_type=DebugType.EXECUTION,
            )
            return SubAgentResult(
                task_result=f"Sub-agent task failed: [{exc.__class__.__name__}] {exc!s}",
                session_id="",
                error=True,
            )


@dataclass
class ActiveTask:
    """Track an in-flight runtime task."""

    task_id: str
    operation_id: str
    task: asyncio.Task[None]
    session_id: str


def _clone_llm_client(client: LLMClientABC) -> LLMClientABC:
    return create_llm_client(client.get_llm_config().model_copy(deep=True))


def _clone_llm_clients(template: LLMClients) -> LLMClients:
    return LLMClients(
        main=_clone_llm_client(template.main),
        main_model_alias=template.main_model_alias,
        sub_clients={sub_agent_type: _clone_llm_client(client) for sub_agent_type, client in template.sub_clients.items()},
        compact=_clone_llm_client(template.compact) if template.compact is not None else None,
    )


class SessionAgentExecutor:
    """Coordinate agent lifecycle and in-flight tasks for operation execution."""

    def __init__(
        self,
        *,
        emit_event: Callable[[events.Event], Awaitable[None]],
        llm_clients: LLMClients,
        model_profile_provider: ModelProfileProvider,
        sub_agent_manager: SubAgentExecutor,
        on_child_task_state_change: Callable[[str, str, bool], None],
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
        self._request_user_interaction_callback = request_user_interaction
        self._session_llm_clients: dict[str, LLMClients] = {}
        self._agents: dict[str, Agent] = {}
        self._primary_session_id: str | None = None
        self._tasks: dict[str, ActiveTask] = {}
        self._operation_task_ids: dict[str, str] = {}

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

    def _ensure_session_llm_clients(self, session: Session) -> LLMClients:
        existing = self._session_llm_clients.get(session.id)
        if existing is not None:
            return existing

        clients = _clone_llm_clients(self._llm_clients_template)
        config = load_config()

        model_config_name = session.model_config_name
        if model_config_name is not None:
            with contextlib.suppress(ValueError):
                model_config = config.get_model_config(model_config_name)
                clients.main = create_llm_client(model_config)
                clients.main_model_alias = model_config_name

        if session.model_thinking is not None:
            clients.main.get_llm_config().thinking = session.model_thinking.model_copy(deep=True)

        self._session_llm_clients[session.id] = clients
        return clients

    def get_session_llm_clients(self, session_id: str) -> LLMClients:
        clients = self._session_llm_clients.get(session_id)
        if clients is None:
            raise RuntimeError(f"Missing session llm clients for session {session_id}")
        return clients

    def set_session_main_client(self, *, session_id: str, client: LLMClientABC, model_alias: str) -> None:
        clients = self.get_session_llm_clients(session_id)
        clients.main = client
        clients.main_model_alias = model_alias

    def get_active_task(self, operation_id: str) -> ActiveTask | None:
        task_id = self._operation_task_ids.get(operation_id)
        if task_id is None:
            return None
        return self._tasks.get(task_id)

    def list_active_tasks(self) -> list[ActiveTask]:
        return list(self._tasks.values())

    def clear_active_tasks(self) -> None:
        self._tasks.clear()
        self._operation_task_ids.clear()

    def _register_task(self, *, operation_id: str, task_id: str, task: asyncio.Task[None], session_id: str) -> None:
        self._tasks[task_id] = ActiveTask(
            task_id=task_id,
            operation_id=operation_id,
            task=task,
            session_id=session_id,
        )
        self._operation_task_ids[operation_id] = task_id

    def _remove_task(self, task_id: str) -> None:
        active = self._tasks.pop(task_id, None)
        if active is None:
            return
        current = self._operation_task_ids.get(active.operation_id)
        if current == task_id:
            self._operation_task_ids.pop(active.operation_id, None)

    def _cancel_tasks_for_sessions(self, session_ids: set[str] | None) -> list[tuple[str, asyncio.Task[None]]]:
        tasks_to_cancel: list[tuple[str, asyncio.Task[None]]] = []
        for task_id, active in list(self._tasks.items()):
            if active.task.done():
                continue
            if session_ids is None or active.session_id in session_ids:
                tasks_to_cancel.append((task_id, active.task))
        return tasks_to_cancel

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
        self._session_llm_clients.pop(session_id, None)
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

        session_clients = self._ensure_session_llm_clients(session)

        profile = self._model_profile_provider.build_profile(session_clients.main)
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

        existing_active = self.get_active_task(operation.id)
        if existing_active is not None and not existing_active.task.done():
            raise RuntimeError(f"Active task already registered for operation {operation.id}")

        task_id = uuid4().hex
        task: asyncio.Task[None] = asyncio.create_task(
            self._run_agent_task(agent, operation.input, task_id, operation.session_id)
        )
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
        task: asyncio.Task[None] = asyncio.create_task(
            self._run_bash_task(
                session=agent.session,
                command=operation.command,
                task_id=task_id,
                session_id=operation.session_id,
            )
        )
        self._register_task(
            operation_id=operation.id,
            task_id=task_id,
            task=task,
            session_id=operation.session_id,
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
        task: asyncio.Task[None] = asyncio.create_task(
            self._run_agent_task(agent, empty_input, task_id, operation.session_id)
        )
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
        task: asyncio.Task[None] = asyncio.create_task(
            self._run_compaction_task(agent, operation, task_id, operation.session_id)
        )
        self._register_task(
            operation_id=operation.id,
            task_id=task_id,
            task=task,
            session_id=operation.session_id,
        )

    async def clear_session(self, session_id: str) -> None:
        agent = await self.ensure_agent(session_id)
        old_session_id = agent.session.id
        session_clients = self.get_session_llm_clients(old_session_id)
        new_session = Session.create(work_dir=agent.session.work_dir)
        new_session.model_name = agent.session.model_name
        new_session.model_config_name = agent.session.model_config_name
        new_session.model_thinking = agent.session.model_thinking

        new_agent = Agent(
            session=new_session,
            profile=self._model_profile_provider.build_profile(session_clients.main),
            compact_llm_client=session_clients.compact,
            request_user_interaction=self._build_request_user_interaction_callback(session_id=new_session.id),
        )
        self._session_llm_clients.pop(old_session_id, None)
        self._session_llm_clients[new_session.id] = session_clients
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
                llm_config=session_clients.main.get_llm_config(),
                loaded_skills=get_loaded_skill_names_by_location(),
                loaded_skill_warnings=get_loaded_skill_warnings_by_location(),
                loaded_memories=get_existing_memory_paths_by_location(work_dir=new_agent.session.work_dir),
            )
        )

    async def interrupt(self, target_session_id: str | None) -> None:
        if target_session_id is not None:
            session_ids = [target_session_id]
        else:
            session_ids = sorted({active.session_id for active in self.list_active_tasks()})
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

        tasks_to_cancel = self._cancel_tasks_for_sessions(session_filter)

        scope = target_session_id or "all"
        log_debug(
            f"Interrupting {len(tasks_to_cancel)} task(s) for: {scope}",
            style="yellow",
            debug_type=DebugType.EXECUTION,
        )

        for task_id, task in tasks_to_cancel:
            task.cancel()
            self._remove_task(task_id)

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
            self._remove_task(task_id)
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
            self._remove_task(task_id)

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
            self._remove_task(task_id)

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


class OperationExecutor:
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
        model_profile_provider: ModelProfileProvider | None = None,
        on_model_change: Callable[[str], None] | None = None,
    ):
        self.event_bus = event_bus
        self.llm_clients: LLMClients = llm_clients

        resolved_profile_provider = model_profile_provider or DefaultModelProfileProvider()
        self.model_profile_provider: ModelProfileProvider = resolved_profile_provider

        self._sub_agent_executor = SubAgentExecutor(self.emit_event, llm_clients, resolved_profile_provider)
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
        self._child_task_state_change_callback: Callable[[str, str, bool], None] | None = None
        self._session_executor = SessionAgentExecutor(
            emit_event=self.emit_event,
            llm_clients=llm_clients,
            model_profile_provider=resolved_profile_provider,
            sub_agent_manager=self._sub_agent_executor,
            on_child_task_state_change=self._on_child_task_state_change,
            request_user_interaction=self.request_user_interaction,
        )
        self._model_switcher = ModelSwitcher(resolved_profile_provider)

    def set_close_session_callback(self, callback: Callable[[str, bool], Awaitable[bool]]) -> None:
        self._close_session_callback = callback

    def set_child_task_state_change_callback(self, callback: Callable[[str, str, bool], None] | None) -> None:
        self._child_task_state_change_callback = callback

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

    def _on_child_task_state_change(self, session_id: str, task_id: str, is_active: bool) -> None:
        callback = self._child_task_state_change_callback
        if callback is None:
            return
        callback(session_id, task_id, is_active)

    async def emit_event(self, event: events.Event) -> None:
        """Publish an event to the runtime event bus."""
        await self.event_bus.publish(event)

    def current_session_id(self) -> str | None:
        """Return the primary active session id, if any.

        This is a convenience wrapper used by the CLI, which conceptually
        operates on a single interactive session per process.
        """

        return self._session_executor.current_session_id()

    @property
    def current_agent(self) -> Agent | None:
        """Return the currently active agent, if any."""

        return self._session_executor.current_agent

    def drop_session_state(self, session_id: str) -> None:
        self._session_executor.drop_session(session_id)

    async def handle_init_agent(self, operation: op.InitAgentOperation) -> None:
        """Initialize an agent for a session and replay history to UI."""
        await self._session_executor.init_agent(operation.session_id)

    async def handle_run_agent(self, operation: op.RunAgentOperation) -> None:
        await self._session_executor.run_agent(operation)

    async def handle_run_bash(self, operation: op.RunBashOperation) -> None:
        await self._session_executor.run_bash(operation)

    async def handle_continue_agent(self, operation: op.ContinueAgentOperation) -> None:
        await self._session_executor.continue_agent(operation)

    async def handle_compact_session(self, operation: op.CompactSessionOperation) -> None:
        await self._session_executor.compact_session(operation)

    async def handle_change_model(self, operation: op.ChangeModelOperation) -> None:
        agent = await self._session_executor.ensure_agent(operation.session_id)
        llm_config, llm_client_name = await self._model_switcher.change_model(
            agent,
            model_name=operation.model_name,
            save_as_default=operation.save_as_default,
        )
        self._session_executor.set_session_main_client(
            session_id=agent.session.id,
            client=agent.profile.llm_client,
            model_alias=llm_client_name,
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

        if self._on_model_change is not None and self.current_session_id() == agent.session.id:
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
        agent = await self._session_executor.ensure_agent(operation.session_id)

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
        agent = await self._session_executor.ensure_agent(operation.session_id)
        session_clients = self._session_executor.get_session_llm_clients(agent.session.id)
        config = load_config()

        helper = SubAgentModelHelper(config)

        sub_agent_type = operation.sub_agent_type
        model_name = operation.model_name

        if model_name is None:
            # Clear explicit override and revert to sub-agent default behavior.
            behavior = helper.describe_empty_model_config_behavior(
                sub_agent_type,
                main_model_name=session_clients.main.model_name,
            )

            # Default: inherit from Agent/main client behavior.
            session_clients.sub_clients.pop(sub_agent_type, None)

            display_model = f"({behavior.description})"
        else:
            # Create new client for the sub-agent
            llm_config = config.get_model_config(model_name)
            new_client = create_llm_client(llm_config)
            session_clients.sub_clients[sub_agent_type] = new_client
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
        agent = await self._session_executor.ensure_agent(operation.session_id)
        session_clients = self._session_executor.get_session_llm_clients(agent.session.id)
        config = load_config()

        model_name = operation.model_name

        if model_name is None:
            # Clear explicit override and use main client for compaction
            session_clients.compact = None
            agent.compact_llm_client = None
            display_model = "(inherit from main agent)"
        else:
            # Create new client for compaction
            llm_config = config.get_model_config(model_name)
            new_client = create_llm_client(llm_config)
            session_clients.compact = new_client
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
        await self._session_executor.clear_session(operation.session_id)

    async def handle_export_session(self, operation: op.ExportSessionOperation) -> None:
        agent = await self._session_executor.ensure_agent(operation.session_id)
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

        await self._session_executor.interrupt(operation.target_session_id)
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

        return self._session_executor.get_active_task(operation_id)

    def list_active_tasks(self) -> list[ActiveTask]:
        return self._session_executor.list_active_tasks()

    def clear_active_tasks(self) -> None:
        self._session_executor.clear_active_tasks()


# Static type check: OperationExecutor must satisfy OperationHandler protocol.
# If this line causes a type error, OperationExecutor is missing required methods.
_: type[OperationHandler] = OperationExecutor
