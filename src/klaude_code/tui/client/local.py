"""In-process RuntimeClient; execution and terminal share one lifetime."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path
from threading import Event
from typing import Any
from uuid import uuid4

from klaude_code.agent.runtime.llm import FallbackLLMClient
from klaude_code.app.peer_endpoint import PeerEndpoint, locate_session
from klaude_code.app.ports import DisplayABC
from klaude_code.app.runtime import AppComponents, AppInitConfig, cleanup_app_components, initialize_app_components
from klaude_code.app.scheduler import HeadlessRuntime
from klaude_code.app.session_index import load_session_summary_from_meta
from klaude_code.app.session_lease import SessionInUseError
from klaude_code.app.session_state import live_descendant_session_ids
from klaude_code.config import config_revision, load_config
from klaude_code.config.model_catalog import build_model_catalog_entry
from klaude_code.log import log_debug
from klaude_code.protocol import events, op
from klaude_code.protocol.background_task import TaskRequest, TaskResponse
from klaude_code.protocol.model_catalog import ModelCatalog
from klaude_code.protocol.peer import PeerMessage, PeerReceipt
from klaude_code.session.session import Session
from klaude_code.session.store_registry import get_store_for_path
from klaude_code.tui.client.base import SessionInfoSnapshot
from klaude_code.tui.diagnostics import diagnostic_phase, log_event_stage
from klaude_code.tui.workspace import active_work_dir


class LocalRuntimeClient(DisplayABC):
    def __init__(
        self,
        session_id: str | None,
        *,
        on_envelope: Callable[[events.EventEnvelope], Awaitable[None]],
        on_session_info: Callable[[SessionInfoSnapshot], None] | None = None,
        on_locate: Callable[[], None] | None = None,
        model: str | None = None,
        debug: bool = False,
        vanilla: bool = False,
        work_dir: Path | None = None,
        unattended: bool = False,
    ) -> None:
        self._session_id = session_id or uuid4().hex
        self._work_dir = (work_dir or active_work_dir()).resolve()
        self._model = model
        self._unattended = unattended
        self._init_config = AppInitConfig(model=model, debug=debug, vanilla=vanilla)
        self._on_envelope = on_envelope
        self._on_session_info = on_session_info
        self._on_locate = on_locate
        self._components: AppComponents | None = None
        self._scheduler: HeadlessRuntime | None = None
        self._endpoint: PeerEndpoint | None = None
        self._display_queue: asyncio.Queue[events.EventEnvelope] = asyncio.Queue()
        self._display_task: asyncio.Task[None] | None = None
        self._state_changed = asyncio.Event()
        self._replay_complete = asyncio.Event()
        self._interactions: asyncio.Queue[events.UserInteractionRequestEvent] = asyncio.Queue()
        self._interaction_closed: dict[tuple[str, str], Event] = {}
        self._info = SessionInfoSnapshot(session_id=self._session_id)
        self._active_operation_id: str | None = None
        self._interrupt_prefill: str | None = None
        self._my_operations: set[str] = set()

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def components(self) -> AppComponents:
        if self._components is None:
            raise RuntimeError("Local runtime is not started")
        return self._components

    async def start(self) -> None:
        # initialize_app_components also starts this display bridge.
        if self._components is not None:
            return
        with diagnostic_phase("local.initialize_components", self.session_id):
            self._components = await initialize_app_components(init_config=self._init_config, display=self)
        try:
            with diagnostic_phase("local.start_scheduler", self.session_id):
                self._scheduler = HeadlessRuntime(self.components.runtime)
                self._scheduler.start(self.components.event_bus)
            with diagnostic_phase("local.initialize_session", self.session_id):
                await self._initialize_session()
            with diagnostic_phase("local.start_peer", self.session_id):
                self._endpoint = PeerEndpoint(self.components.runtime, self._scheduler, on_locate=self._on_locate)
                await self._endpoint.start()
        except BaseException:
            await self.close()
            raise

    async def _claim_session(self, session_id: str) -> None:
        try:
            self.components.runtime.claim_session(session_id)
        except SessionInUseError:
            await locate_session(session_id)
            raise

    async def _initialize_session(self) -> None:
        await self._claim_session(self.session_id)
        if not Session.exists(self.session_id, work_dir=self._work_dir):
            session = Session.create(id=self.session_id, work_dir=self._work_dir)
            session.model_config_name = self._model
            session.vanilla = self._init_config.vanilla
            session.unattended = self._unattended
            await asyncio.to_thread(session.ensure_meta_exists)
        else:
            updates: dict[str, Any] = {"unattended": self._unattended}
            if self._model is not None:
                updates.update({"model_config_name": self._model, "model_from_role": False})
            await asyncio.to_thread(
                get_store_for_path(self._work_dir).update_meta,
                self.session_id,
                updates,
            )
        summary = load_session_summary_from_meta(
            get_store_for_path(self._work_dir).load_meta(self.session_id) or {},
            fallback_session_id=self.session_id,
        )
        if summary is not None and self._scheduler is not None:
            self._scheduler.restore([summary], schedule=False)
        await self.components.runtime.submit_and_wait(
            op.InitAgentOperation(session_id=self.session_id, work_dir=self._work_dir)
        )
        actor = self.components.runtime.session_registry.get_session_actor(self.session_id)
        if actor is None or actor.get_agent() is None:
            raise RuntimeError("Local session initialization failed")
        await self.components.wait_for_display_idle()
        self._refresh_info()
        self._replay_complete.set()

    async def stop(self) -> None:
        # The application owns the bridge; the runner owns the terminal display.
        pass

    async def close(self) -> None:
        for closed in self._interaction_closed.values():
            closed.set()
        components = self._components
        if components is None:
            return
        try:
            try:
                if self._endpoint is not None:
                    await self._endpoint.close()
                    self._endpoint = None
                actor = components.runtime.session_registry.get_session_actor(self.session_id)
                if actor is not None and actor.get_agent() is not None and self.has_running_tasks():
                    await components.runtime.submit_and_wait(op.StopAllTasksOperation(session_id=self.session_id))
            finally:
                try:
                    if self._scheduler is not None:
                        await self._scheduler.aclose()
                finally:
                    await cleanup_app_components(components)
            await self.wait_for_display_idle()
        finally:
            self._components = None
            if self._display_task is not None:
                self._display_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self._display_task

    def has_running_tasks(self) -> bool:
        return self.components.runtime.has_running_tasks() or bool(
            self._scheduler is not None
            and (
                self._scheduler.continuation(self.session_id).automatic
                or self._scheduler.is_running(self.session_id)
                or self._scheduler.turn_start_pending(self.session_id)
            )
        )

    async def switch_session(self, session_id: str) -> None:
        if self.has_running_tasks():
            raise ValueError("Stop running tasks with /stop before switching sessions")
        await self._claim_session(session_id)
        registry = self.components.runtime.session_registry
        for child_id in live_descendant_session_ids(registry, self.session_id):
            actor = registry.get_session_actor(child_id)
            agent = actor.get_agent() if actor is not None else None
            if agent is not None:
                await agent.session.wait_for_flush()
            if not await self.components.runtime.close_session(child_id):
                raise ValueError("Stop running tasks with /stop before switching sessions")
        await self.command_agent().session.wait_for_flush()
        if not await self.components.runtime.close_session(self.session_id):
            raise ValueError("Stop running tasks with /stop before switching sessions")
        self._session_id = session_id
        self._model = None
        self._info = SessionInfoSnapshot(session_id=session_id)
        self._replay_complete.clear()
        await self._initialize_session()

    async def create_session(self) -> str:
        if self.has_running_tasks():
            raise ValueError("Stop running tasks with /stop before switching sessions")
        session = Session.create(work_dir=self._work_dir)
        session.model_config_name = self._info.model_config_name
        session.vanilla = self._init_config.vanilla
        await asyncio.to_thread(session.ensure_meta_exists)
        return session.id

    def start_display(self) -> None:
        if self._display_task is None:
            self._display_task = asyncio.create_task(self._display_loop())

    async def _display_loop(self) -> None:
        while True:
            envelope = await self._display_queue.get()
            try:
                log_event_stage("local.display_dequeued", envelope)
                await self._on_envelope(envelope)
            except Exception as exc:
                log_debug(f"Local display consumer failed: {exc}")
            finally:
                self._display_queue.task_done()

    async def wait_for_display_idle(self) -> None:
        if self._components is not None:
            await self.components.wait_for_display_idle()
        if self._display_task is not None:
            await self._display_queue.join()

    async def wait_for_replay_complete(self) -> None:
        await self._replay_complete.wait()

    async def consume_envelope(self, envelope: events.EventEnvelope) -> None:
        event = envelope.event
        log_event_stage("local.consume", envelope)
        if not self._replay_complete.is_set():
            self._info.replay_through_event_seq = max(self._info.replay_through_event_seq, envelope.event_seq)
        if self._endpoint is not None:
            self._endpoint.observe(event)
        if isinstance(event, events.UserInteractionRequestEvent):
            self._interaction_closed[(event.session_id, event.request_id)] = Event()
            self._interactions.put_nowait(event)
        elif isinstance(event, events.UserInteractionResolvedEvent | events.UserInteractionCancelledEvent):
            self._interaction_closed.setdefault((event.session_id, event.request_id), Event()).set()
        if event.session_id == self.session_id:
            if isinstance(event, events.TaskStartEvent):
                self._active_operation_id = envelope.operation_id
            elif isinstance(event, events.TaskFinishEvent | events.InterruptEvent) or (
                isinstance(event, events.OperationFinishedEvent) and event.operation_id == self._active_operation_id
            ):
                self._active_operation_id = None
            elif isinstance(event, events.UserMessageRetractedEvent) and envelope.operation_id in self._my_operations:
                self._interrupt_prefill = event.content
            with diagnostic_phase("local.refresh_info", event.session_id, envelope=envelope, slow_only=True):
                self._refresh_info()
        if self._endpoint is not None and isinstance(
            event,
            events.SessionStatusEvent
            | events.OperationFinishedEvent
            | events.TaskStartEvent
            | events.SessionTitleChangedEvent,
        ):
            with diagnostic_phase("local.refresh_peer", event.session_id, envelope=envelope, slow_only=True):
                self._endpoint.refresh()
        log_event_stage("local.display_enqueue", envelope)
        await self._display_queue.put(envelope)

    def _refresh_info(self) -> None:
        self._info.is_replay_snapshot = not self._replay_complete.is_set()
        runtime = self.components.runtime
        actor = runtime.session_registry.get_session_actor(self.session_id)
        agent = actor.get_agent() if actor is not None else None
        if agent is not None:
            session = agent.session
            llm = agent.profile.llm_client.get_llm_config()
            self._info.model_config_name = session.model_config_name
            self._info.active_model_name = llm.model_id
            if isinstance(agent.profile.llm_client, FallbackLLMClient):
                self._info.active_model_name = agent.profile.llm_client.active_candidate.selector.split("@", 1)[0]
            self._info.provider_name = llm.provider_name
            self._info.effort = llm.effective_effort
            self._info.work_dir = str(session.work_dir)
            self._info.title = session.title
            self._info.steering = tuple(item.text for item in agent.steering_snapshot())
            self._info.follow_ups = tuple(item.text for item in agent.follow_up_snapshot())
        if self._scheduler is not None:
            self._info.status = self._scheduler.session_status(self.session_id)
            self._info.state = self._info.status.category
        self._state_changed.set()
        if self._on_session_info is not None:
            self._on_session_info(self._info)

    def command_agent(self):
        actor = self.components.runtime.session_registry.get_session_actor(self.session_id)
        agent = actor.get_agent() if actor is not None else None
        if agent is None:
            raise RuntimeError("Local session is not initialized")
        return agent

    async def submit(self, operation: op.Operation) -> str:
        self._my_operations.add(operation.id)
        if isinstance(operation, op.RunAgentOperation) and self._scheduler is not None:
            self._scheduler.mark_session_active(operation.session_id)
            self._scheduler.mark_turn_starting(operation.session_id, operation.id)
        return await self.components.runtime.submit(operation)

    async def wait_for(self, operation_id: str) -> None:
        await self.components.runtime.wait_for(operation_id)

    async def submit_and_wait(self, operation: op.Operation) -> None:
        await self.submit(operation)
        status = await self.components.runtime.wait_for(operation.id)
        if status != "completed":
            raise RuntimeError(f"{operation.type.value} {status or 'did not finish'}")

    async def emit_user_message(self, event: events.UserMessageEvent) -> None:
        await self.components.event_bus.publish(event)

    async def emit_local_event(self, event: events.Event) -> None:
        await self.components.event_bus.publish(event)

    async def dequeue_pending_messages(self) -> tuple[str, ...]:
        actor = self.components.runtime.session_registry.get_session_actor(self.session_id)
        agent = actor.get_agent() if actor is not None else None
        if agent is None:
            return ()
        texts = tuple(item.text for item in agent.pop_all_steering())
        texts += tuple(item.text for item in agent.pop_all_follow_up())
        await agent.session.wait_for_flush()
        await self.components.event_bus.publish(
            events.SteeringQueueUpdatedEvent(
                session_id=self.session_id, texts=[item.text for item in agent.steering_snapshot()]
            )
        )
        await self.components.event_bus.publish(
            events.FollowUpQueueChangedEvent(
                session_id=self.session_id, texts=[item.text for item in agent.follow_up_snapshot()]
            )
        )
        return texts

    async def get_model_catalog(self) -> ModelCatalog:
        config = load_config()
        return ModelCatalog(
            models=[
                build_model_catalog_entry(entry)
                for entry in config.iter_model_entries(only_available=True, include_disabled=False)
            ],
            revision=config_revision(),
        )

    async def manage_tasks(self, request: TaskRequest) -> TaskResponse:
        return await self.components.runtime.task_manager.manage(self.session_id, self._work_dir, request)

    async def send_task_message(self, task_id: str, body: str) -> PeerReceipt:
        tasks = (await self.manage_tasks(TaskRequest(action="list"))).tasks
        task = next((task for task in tasks if task.ref.task_id == task_id), None)
        if (
            task is None
            or task.ref.kind != "agent"
            or not task.ref.session_id
            or task.status != "running"
            or not task.ref.operation_id
        ):
            raise ValueError("Selected child agent is no longer running")
        assert self._scheduler is not None
        return await self._scheduler.deliver_peer(
            PeerMessage(recipient=task.ref.session_id, sender_label="TUI task panel (external)", body=body),
            self._work_dir,
            expected_operation_id=task.ref.operation_id,
        )

    def is_running(self) -> bool:
        return self._info.status.execution in {"queued", "running"}

    def active_operation_id(self) -> str | None:
        return self._active_operation_id

    def steering_texts(self) -> tuple[str, ...]:
        return self._info.steering

    def follow_up_texts(self) -> tuple[str, ...]:
        return self._info.follow_ups

    def optimistically_append_follow_ups(self, texts: Sequence[str]) -> None:
        self._info.follow_ups = (*self._info.follow_ups, *texts)
        self._state_changed.set()

    def remove_optimistic_follow_up(self, text: str) -> None:
        texts = list(self._info.follow_ups)
        for i in range(len(texts) - 1, -1, -1):
            if texts[i] == text:
                del texts[i]
                break
        self._info.follow_ups = tuple(texts)
        self._state_changed.set()

    def optimistically_append_steering(self, texts: Sequence[str]) -> None:
        self._info.steering = (*self._info.steering, *texts)
        self._state_changed.set()

    def remove_optimistic_steering(self, text: str) -> None:
        texts = list(self._info.steering)
        for i in range(len(texts) - 1, -1, -1):
            if texts[i] == text:
                del texts[i]
                break
        self._info.steering = tuple(texts)
        self._state_changed.set()

    def session_info(self) -> SessionInfoSnapshot:
        return self._info

    def consume_interrupt_prefill(self) -> str | None:
        text, self._interrupt_prefill = self._interrupt_prefill, None
        return text

    def state_changed_event(self) -> asyncio.Event:
        return self._state_changed

    def interaction_requests(self) -> asyncio.Queue[events.UserInteractionRequestEvent]:
        return self._interactions

    def interaction_closed_event(self, request: events.UserInteractionRequestEvent) -> Event:
        return self._interaction_closed[(request.session_id, request.request_id)]
