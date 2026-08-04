"""Headless run management: concurrency slots, run queue, and activity tracking.

`klaude run` spawns background agents through this module. The server keeps a
global cap on concurrently running headless sessions; runs beyond the cap wait
in an in-memory queue (state `queued`) until a slot frees. The queue does not
survive a server restart — queued sessions exist on disk and can be re-run via
`klaude send`.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from klaude_code.app.runtime_facade import RuntimeFacade
from klaude_code.control.event_bus import EventBus, EventSubscription
from klaude_code.log import DebugType, log_debug
from klaude_code.protocol import events, op
from klaude_code.protocol.message import UserInputPayload
from klaude_code.server.session_tape import SessionEventTapes

_ACTIVITY_ARG_KEYS = (
    "command",
    "file_path",
    "path",
    "pattern",
    "prompt",
    "description",
    "url",
    "question",
    "skill",
)


def format_tool_call_activity(tool_name: str, arguments: str, *, max_len: int = 80) -> str:
    """Render a tool call as a one-line activity label, e.g. ``Bash: uv run pytest``."""
    detail = ""
    try:
        parsed: Any = json.loads(arguments)
    except (json.JSONDecodeError, TypeError):
        parsed = None
    if isinstance(parsed, dict):
        for key in _ACTIVITY_ARG_KEYS:
            value = parsed.get(key)
            if isinstance(value, str) and value.strip():
                detail = value.strip()
                break
        else:
            detail = json.dumps(parsed, ensure_ascii=False)
    elif arguments:
        detail = arguments
    detail = " ".join(detail.split())
    label = f"{tool_name}: {detail}" if detail else tool_name
    if len(label) > max_len:
        label = label[: max_len - 1] + "…"
    return label


@dataclass
class _SessionActivity:
    current_tool_call: tuple[str, str] | None = None  # (tool_name, arguments)
    failed: bool = False
    interrupted: bool = False
    finished_at: float | None = None


class SessionActivityTracker:
    """Tracks per-session live activity from the event stream.

    - current tool call: last ToolCallEvent, cleared on turn boundaries
    - failed: last turn ended with an ErrorEvent (cleared on the next turn)
    """

    def __init__(self) -> None:
        self._by_session: dict[str, _SessionActivity] = {}

    def _entry(self, session_id: str) -> _SessionActivity:
        entry = self._by_session.get(session_id)
        if entry is None:
            entry = _SessionActivity()
            self._by_session[session_id] = entry
        return entry

    def consume(self, event: events.Event) -> None:
        session_id = event.session_id
        if not session_id or session_id == "__app__":
            return
        if isinstance(event, events.ToolCallEvent):
            entry = self._entry(session_id)
            entry.current_tool_call = (event.tool_name, event.arguments)
            return
        if isinstance(event, events.TaskStartEvent | events.UserMessageEvent):
            entry = self._entry(session_id)
            entry.failed = False
            entry.interrupted = False
            entry.current_tool_call = None
            entry.finished_at = None
            return
        if isinstance(event, events.InterruptEvent):
            entry = self._entry(session_id)
            # An Esc that resumes the queue is not a stop: leaving the flag
            # set would block the follow-up drain this interrupt asked for.
            entry.interrupted = not event.resume_follow_ups
            entry.current_tool_call = None
            entry.finished_at = time.time()
            return
        if isinstance(event, events.TaskFinishEvent):
            entry = self._entry(session_id)
            entry.current_tool_call = None
            entry.finished_at = time.time()
            return
        if isinstance(event, events.ErrorEvent):
            entry = self._entry(session_id)
            entry.failed = True
            entry.current_tool_call = None
            entry.finished_at = time.time()

    def current_tool_call(self, session_id: str) -> tuple[str, str] | None:
        entry = self._by_session.get(session_id)
        return entry.current_tool_call if entry is not None else None

    def is_failed(self, session_id: str) -> bool:
        entry = self._by_session.get(session_id)
        return entry.failed if entry is not None else False

    def is_interrupted(self, session_id: str) -> bool:
        entry = self._by_session.get(session_id)
        return entry.interrupted if entry is not None else False


@dataclass
class QueuedRun:
    session_id: str
    prompt: UserInputPayload
    work_dir: Path
    enqueued_at: float = field(default_factory=time.time)


class HeadlessRuntime:
    """Owns the headless run queue, concurrency slots, and activity tracker."""

    def __init__(
        self,
        runtime: RuntimeFacade,
        *,
        max_running: int = 8,
        tapes: SessionEventTapes | None = None,
    ) -> None:
        self._runtime = runtime
        self._tapes = tapes
        self._max_running = max(1, max_running)
        self.tracker = SessionActivityTracker()
        self._running: set[str] = set()
        self._queue: deque[QueuedRun] = deque()
        self._queued_by_id: dict[str, QueuedRun] = {}
        self._watch_tasks: set[asyncio.Task[None]] = set()
        self._consumer_task: asyncio.Task[None] | None = None
        self._drain_locks: dict[str, asyncio.Lock] = {}
        # Sessions with a user turn submitted whose task has not started yet.
        # The registry looks idle in that window; the drain must back off or
        # it would steal the slot and get the user's turn busy-rejected.
        self._turn_starting: dict[str, float] = {}

    @property
    def max_running(self) -> int:
        return self._max_running

    def start(self, event_bus: EventBus) -> None:
        if self._consumer_task is not None:
            return
        self._consumer_task = asyncio.create_task(self._consume_events(event_bus))

    async def aclose(self) -> None:
        tasks = list(self._watch_tasks)
        if self._consumer_task is not None:
            tasks.append(self._consumer_task)
        for task in tasks:
            if not task.done():
                task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._watch_tasks.clear()
        self._consumer_task = None

    async def _consume_events(self, event_bus: EventBus) -> None:
        subscription: EventSubscription = event_bus.subscribe(None)
        while True:
            async for envelope in subscription:
                event = envelope.event
                if isinstance(event, events.EndEvent):
                    return
                self.tracker.consume(event)
                if isinstance(event, events.TaskStartEvent):
                    self._turn_starting.pop(event.session_id, None)
                if isinstance(event, events.TaskFinishEvent) and not self.tracker.is_interrupted(event.session_id):
                    self._schedule_follow_up_drain(event.session_id)
                if isinstance(event, events.TaskFinishEvent):
                    self._schedule_tape_reset(event.session_id)
                # TUI Esc mid-queue: the interrupted turn ends without a
                # drain-triggering TaskFinish, so continue the queue here.
                if isinstance(event, events.InterruptEvent) and event.resume_follow_ups:
                    self._schedule_follow_up_drain(event.session_id)
                # A follow-up queued onto an already-idle session (submit
                # raced the turn end) has no TaskFinish coming; drain now.
                if isinstance(event, events.FollowUpQueueUpdatedEvent) and event.texts:
                    self._schedule_follow_up_drain(event.session_id)
            # Bus dropped this subscriber on overflow; resubscribe.
            log_debug("[headless] activity subscription overflowed; resubscribed", debug_type=DebugType.EVENT_BUS)
            subscription = event_bus.subscribe(None)

    def _schedule_follow_up_drain(self, session_id: str) -> None:
        task = asyncio.create_task(self._drain_follow_up(session_id))
        self._watch_tasks.add(task)
        task.add_done_callback(self._watch_tasks.discard)

    def _schedule_tape_reset(self, session_id: str) -> None:
        if self._tapes is None:
            return
        task = asyncio.create_task(self._reset_tape_after_flush(session_id))
        self._watch_tasks.add(task)
        task.add_done_callback(self._watch_tasks.discard)

    async def _reset_tape_after_flush(self, session_id: str) -> None:
        """Advance the attach-replay tape once the finished turn is on disk."""
        if self._tapes is None:
            return
        registry = self._runtime.session_registry
        agent = None
        for _ in range(100):
            actor = registry.get_session_actor(session_id)
            agent = actor.get_agent() if actor is not None else None
            if actor is None or agent is None:
                return
            if actor.snapshot().is_idle:
                break
            await asyncio.sleep(0.05)
        else:
            return
        if agent is None:
            return
        try:
            # Shield: cancelling this task must not cancel the shared flush
            # future other waiters (e.g. runtime shutdown) are awaiting.
            await asyncio.shield(agent.session.wait_for_flush())
        except asyncio.CancelledError:
            return
        except Exception:
            pass
        actor = registry.get_session_actor(session_id)
        if actor is None or not actor.snapshot().is_idle:
            return
        agent = actor.get_agent()
        if agent is None:
            return
        self._tapes.reset_if_settled(session_id, len(agent.session.conversation_history))

    async def _drain_follow_up(self, session_id: str) -> None:
        """Drain queued follow-up turns on any server-managed session.

        The server owns every session (TUI clients only attach), so the queue
        continues here for interactive and headless sessions alike. A
        per-session lock serializes drains: without it two triggers could pop
        concurrently and lose a message to a busy rejection. Mirrors the old
        in-process runner: compact first when over threshold; stop draining
        after an interrupt (kill must keep the session stopped).
        """
        lock = self._drain_locks.setdefault(session_id, asyncio.Lock())
        async with lock:
            registry = self._runtime.session_registry
            while True:
                agent = None
                for _ in range(100):
                    actor = registry.get_session_actor(session_id)
                    agent = actor.get_agent() if actor is not None else None
                    if actor is None or agent is None:
                        return
                    if actor.snapshot().is_idle:
                        break
                    # The finish event races the operation teardown; wait it out.
                    await asyncio.sleep(0.05)
                else:
                    return
                if agent is None:
                    return
                if self.tracker.is_interrupted(session_id):
                    return
                if self.turn_start_pending(session_id):
                    return
                if agent.peek_next_follow_up() is None:
                    return

                if self._should_compact_before_run(agent):
                    compact = op.CompactSessionOperation(session_id=session_id, reason="threshold", will_retry=False)
                    await self._runtime.submit(compact)
                    await self._runtime.wait_for(compact.id)
                    refreshed = registry.get_session_actor(session_id)
                    agent = refreshed.get_agent() if refreshed is not None else None
                    if agent is None or self.tracker.is_interrupted(session_id):
                        return

                follow_up = agent.pop_next_follow_up()
                if follow_up is None:
                    return
                await self._runtime.emit_event(
                    events.UserMessageEvent(content=follow_up.text, session_id=session_id, images=follow_up.images)
                )
                run = op.RunAgentOperation(session_id=session_id, input=follow_up)
                await self._runtime.submit(run)
                await self._runtime.emit_event(
                    events.FollowUpQueueUpdatedEvent(
                        session_id=session_id,
                        texts=[item.text for item in agent.follow_up_snapshot()],
                    )
                )
                await self._runtime.wait_for(run.id)

    @staticmethod
    def _should_compact_before_run(agent: Any) -> bool:
        from klaude_code.agent.compaction import should_compact_threshold

        try:
            return should_compact_threshold(
                session=agent.session,
                config=None,
                llm_config=agent.profile.llm_client.get_llm_config(),
            )
        except Exception:
            return False

    def mark_turn_starting(self, session_id: str) -> None:
        """Note that a user turn was submitted but its task is not active yet."""
        self._turn_starting[session_id] = time.time()

    def turn_start_pending(self, session_id: str) -> bool:
        started_at = self._turn_starting.get(session_id)
        if started_at is None:
            return False
        if time.time() - started_at > 5.0:
            # The submission never became a task (e.g. rejected); recover.
            self._turn_starting.pop(session_id, None)
            return False
        return True

    def is_queued(self, session_id: str) -> bool:
        return session_id in self._queued_by_id

    def queued_session_ids(self) -> list[str]:
        return [entry.session_id for entry in self._queue]

    async def spawn(self, *, session_id: str, prompt: UserInputPayload, work_dir: Path) -> str:
        """Start a headless run or queue it. Returns "running" or "queued"."""
        entry = QueuedRun(session_id=session_id, prompt=prompt, work_dir=work_dir)
        if len(self._running) >= self._max_running:
            self._queue.append(entry)
            self._queued_by_id[session_id] = entry
            return "queued"
        await self._launch(entry)
        return "running"

    def cancel_queued(self, session_id: str) -> bool:
        entry = self._queued_by_id.pop(session_id, None)
        if entry is None:
            return False
        with contextlib.suppress(ValueError):
            self._queue.remove(entry)
        return True

    async def _launch(self, entry: QueuedRun) -> None:
        session_id = entry.session_id
        self._running.add(session_id)
        try:
            await self._runtime.submit_and_wait(
                op.InitAgentOperation(
                    session_id=session_id,
                    work_dir=entry.work_dir,
                    defer_welcome_context=True,
                    defer_replay=True,
                )
            )
            await self._runtime.emit_event(
                events.UserMessageEvent(
                    content=entry.prompt.text,
                    session_id=session_id,
                    images=entry.prompt.images,
                )
            )
            operation_id = await self._runtime.submit(op.RunAgentOperation(session_id=session_id, input=entry.prompt))
        except Exception:
            self._running.discard(session_id)
            self._queued_by_id.pop(session_id, None)
            self._pump()
            raise
        # Only clear the queued flag after the run operation is accepted so
        # state derivation never reports a spurious `idle` gap.
        self._queued_by_id.pop(session_id, None)
        watch_task = asyncio.create_task(self._watch_run(session_id, operation_id))
        self._watch_tasks.add(watch_task)
        watch_task.add_done_callback(self._watch_tasks.discard)

    async def _watch_run(self, session_id: str, operation_id: str) -> None:
        try:
            await self._runtime.wait_for(operation_id)
        finally:
            self._running.discard(session_id)
            self._pump()

    def _pump(self) -> None:
        while self._queue and len(self._running) < self._max_running:
            entry = self._queue.popleft()
            if entry.session_id not in self._queued_by_id:
                continue  # cancelled while queued
            launch_task = asyncio.create_task(self._launch_logged(entry))
            self._watch_tasks.add(launch_task)
            launch_task.add_done_callback(self._watch_tasks.discard)

    async def _launch_logged(self, entry: QueuedRun) -> None:
        try:
            await self._launch(entry)
        except Exception as exc:
            log_debug(
                f"[headless] queued launch failed session={entry.session_id}: {exc}",
                debug_type=DebugType.EXECUTION,
            )
