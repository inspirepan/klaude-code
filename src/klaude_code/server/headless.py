"""Headless run management: concurrency slots, run queue, and activity tracking.

`klaude run` and later headless turns pass through one persistent slot queue.
Interactive sessions use the same follow-up drain but do not consume headless
slots.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from klaude_code.app.runtime_facade import RuntimeFacade
from klaude_code.control.event_bus import EventBus, EventSubscription
from klaude_code.log import DebugType, log_debug, log_info
from klaude_code.protocol import events, op
from klaude_code.protocol.message import QueuedUserInput, UserInputPayload
from klaude_code.server.session_index import SessionSummary
from klaude_code.server.session_tape import SessionEventTapes
from klaude_code.session.session import Session

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

    def clear_failed(self, session_id: str) -> None:
        entry = self._by_session.get(session_id)
        if entry is not None:
            entry.failed = False

    def is_interrupted(self, session_id: str) -> bool:
        entry = self._by_session.get(session_id)
        return entry.interrupted if entry is not None else False

    def restore_failed(self, session_id: str) -> None:
        self._entry(session_id).failed = True


@dataclass
class QueuedRun:
    session_id: str
    queued: QueuedUserInput
    work_dir: Path
    kind: Literal["turn", "follow_up", "steer"] = "turn"


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
        self._launch_handoffs: dict[str, asyncio.Future[Any]] = {}
        self._consumer_task: asyncio.Task[None] | None = None
        self._closing = False
        self._drain_locks: dict[str, asyncio.Lock] = {}
        self._scheduling_locks: dict[str, asyncio.Lock] = {}
        self._steering: set[str] = set()
        self._stopped_sessions: set[str] = set()
        # Sessions already told (log + NoticeEvent) that their queue is
        # latched; cleared when the latch lifts so the next incident notifies.
        self._drain_latch_noticed: set[str] = set()
        # Sessions with a user turn submitted whose task has not started yet.
        # The registry looks idle in that window; the drain must back off or
        # it would steal the slot and get the user's turn busy-rejected.
        self._turn_starting: dict[str, str] = {}

    @property
    def max_running(self) -> int:
        return self._max_running

    def start(self, event_bus: EventBus) -> None:
        if self._consumer_task is not None:
            return
        self._closing = False
        self._consumer_task = asyncio.create_task(self._consume_events(event_bus))

    def restore(self, summaries: list[SessionSummary]) -> None:
        """Restore durable queued turns, follow-ups, and failed state."""
        restored: list[QueuedRun] = []
        for summary in summaries:
            if summary.spawn_kind != "headless":
                continue
            work_dir = Path(summary.work_dir)
            session = Session.load(summary.id, work_dir=work_dir)
            if session.headless_failed:
                self.tracker.restore_failed(summary.id)
            if session.headless_queued_turn is not None:
                queued_turn = session.headless_queued_turn
                if session.headless_completed_turn_id == queued_turn.id:
                    Session.persist_headless_queued_turn(
                        summary.id,
                        work_dir,
                        expected_turn_id=queued_turn.id,
                    )
                    session.headless_queued_turn = None
                else:
                    restored.append(
                        QueuedRun(
                            session_id=summary.id,
                            queued=queued_turn,
                            work_dir=work_dir,
                        )
                    )
            while session.follow_up_queue and session.headless_completed_turn_id == session.follow_up_queue[0].id:
                session.set_follow_up_queue(session.follow_up_queue[1:])
            if session.headless_queued_turn is None and session.follow_up_queue:
                restored.append(
                    QueuedRun(
                        session_id=summary.id,
                        queued=session.follow_up_queue[0],
                        work_dir=work_dir,
                        kind="follow_up",
                    )
                )
        for entry in sorted(restored, key=lambda item: item.queued.enqueued_at):
            self._enqueue(entry)
        self._pump()

    async def aclose(self) -> None:
        self._closing = True
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
        self._launch_handoffs.clear()
        self._consumer_task = None

    async def _consume_events(self, event_bus: EventBus) -> None:
        subscription: EventSubscription = event_bus.subscribe(None)
        while True:
            async for envelope in subscription:
                event = envelope.event
                if isinstance(event, events.EndEvent):
                    return
                try:
                    await self._consume_one(event)
                except Exception as exc:
                    # This loop is the only holder of every drain trigger on
                    # the server; one bad event must not silently kill queue
                    # draining for all sessions.
                    log_info(
                        f"[headless] event consumer error on {events.event_type_name(event)}: {exc}",
                        debug_type=DebugType.EXECUTION,
                    )
            # Bus dropped this subscriber on overflow; resubscribe.
            log_info("[headless] activity subscription overflowed; resubscribed", debug_type=DebugType.EVENT_BUS)
            subscription = event_bus.subscribe(None)

    async def _consume_one(self, event: events.Event) -> None:
        self.tracker.consume(event)
        if isinstance(event, events.ErrorEvent):
            await self._persist_failed(event.session_id, failed=True)
        if isinstance(event, events.TaskStartEvent):
            self._turn_starting.pop(event.session_id, None)
        if (
            isinstance(event, events.OperationRejectedEvent)
            or (isinstance(event, events.OperationFinishedEvent) and event.status in ("rejected", "failed"))
        ) and self._turn_starting.get(event.session_id) == event.operation_id:
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
        # Background operations (away summary, compaction, ...) hold
        # the actor busy without any TaskFinish. A drain that gave up
        # waiting on them must be re-armed when they complete, or a
        # message queued during the window sits pending forever. A failed
        # operation frees the actor the same way; the failed/stopped
        # latches in _schedule_follow_up_drain keep error loops out.
        if isinstance(event, events.OperationFinishedEvent) and event.status in ("completed", "failed"):
            self._schedule_follow_up_drain(event.session_id)

    def nudge_follow_up_drain(self, session_id: str) -> None:
        """Kick the drain for a session that may hold a persisted queue.

        Interactive sessions are not covered by restore(): a queue persisted
        before a server restart or an actor reclaim has no event-driven drain
        trigger left. Attach and rehydration call this so the queue runs.
        Both are explicit client actions, so they also lift the kill/failed
        latches (revive).
        """
        self._schedule_follow_up_drain(session_id, revive=True)

    def mark_session_active(self, session_id: str) -> None:
        """Lift the kill/failed latches without scheduling a drain.

        Used right before a user turn submit: the turn's own lifecycle events
        re-arm the drain, and scheduling one here could race the submit for
        the idle slot.
        """
        self._stopped_sessions.discard(session_id)
        self.tracker.clear_failed(session_id)
        self._drain_latch_noticed.discard(session_id)

    def _schedule_follow_up_drain(self, session_id: str, *, revive: bool = False) -> None:
        if revive:
            self.mark_session_active(session_id)
        if session_id in self._stopped_sessions or self.tracker.is_failed(session_id):
            self._notify_drain_latched(session_id)
            return
        self._drain_latch_noticed.discard(session_id)
        actor = self._runtime.session_registry.get_session_actor(session_id)
        agent = actor.get_agent() if actor is not None else None
        if agent is not None and agent.session.spawn_kind == "headless":
            queued = agent.peek_next_follow_up_record()
            if queued is not None:
                self._enqueue(
                    QueuedRun(
                        session_id=session_id,
                        queued=queued,
                        work_dir=agent.session.work_dir,
                        kind="follow_up",
                    )
                )
                self._pump()
            return
        task = asyncio.create_task(self._drain_follow_up_logged(session_id))
        self._watch_tasks.add(task)
        task.add_done_callback(self._watch_tasks.discard)

    async def _drain_follow_up_logged(self, session_id: str) -> None:
        try:
            await self._drain_follow_up(session_id)
        except Exception as exc:
            # A drained turn that errors raises out of _start_turn; without
            # this the exception dies unobserved in the fire-and-forget task.
            log_info(
                f"[headless] follow-up drain aborted session={session_id[:8]}: {exc}",
                debug_type=DebugType.EXECUTION,
            )

    def _notify_drain_latched(self, session_id: str) -> None:
        """Surface a latched queue instead of dropping the trigger silently.

        Pre-latch behavior was invisible: the TUI kept showing "N pending"
        with no reason why nothing ran. Logged always; the NoticeEvent tells
        attached clients how to resume. Notified once per latch episode.
        """
        actor = self._runtime.session_registry.get_session_actor(session_id)
        agent = actor.get_agent() if actor is not None else None
        if agent is None or agent.peek_next_follow_up() is None:
            return
        if session_id in self._drain_latch_noticed:
            return
        self._drain_latch_noticed.add(session_id)
        reason = "session was stopped" if session_id in self._stopped_sessions else "last turn failed"
        log_info(
            f"[headless] follow-up queue latched ({reason}), {agent.follow_up_count()} pending: {session_id[:8]}",
            debug_type=DebugType.EXECUTION,
        )
        notice = events.NoticeEvent(
            session_id=session_id,
            content=f"Queued messages are paused: {reason}. They resume on your next message.",
            is_error=True,
        )
        task = asyncio.create_task(self._runtime.emit_event(notice))
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
                    # OperationFinished of whatever holds the actor busy
                    # re-arms the drain (see _consume_one).
                    log_info(
                        f"[headless] drain gave up waiting for idle: {session_id[:8]}",
                        debug_type=DebugType.EXECUTION,
                    )
                    return
                if agent is None:
                    return
                if self.tracker.is_interrupted(session_id):
                    log_info(f"[headless] drain skip (interrupted): {session_id[:8]}", debug_type=DebugType.EXECUTION)
                    return
                if self.turn_start_pending(session_id):
                    log_debug(
                        f"[headless] drain skip (turn starting): {session_id[:8]}", debug_type=DebugType.EXECUTION
                    )
                    return
                if agent.peek_next_follow_up() is None:
                    return

                if not await self._run_one_follow_up(agent):
                    return

    async def _run_headless_follow_up(self, entry: QueuedRun) -> None:
        agent = await self._ensure_agent(entry.session_id, entry.work_dir)
        if not self.tracker.is_interrupted(entry.session_id):
            await self._run_one_follow_up(agent)

    async def _run_one_follow_up(self, agent: Any) -> bool:
        """Run and acknowledge one durable follow-up after its history flush."""
        session_id = agent.session.id
        queued: QueuedUserInput | None = agent.peek_next_follow_up_record()
        if queued is None:
            return False
        if self._should_compact_before_run(agent):
            compact = op.CompactSessionOperation(session_id=session_id, reason="threshold", will_retry=False)
            await self._runtime.submit(compact)
            await self._runtime.wait_for(compact.id)
            actor = self._runtime.session_registry.get_session_actor(session_id)
            agent = actor.get_agent() if actor is not None else None
            if agent is None or self.tracker.is_interrupted(session_id):
                return False
            queued = agent.peek_next_follow_up_record()
            if queued is None:
                return False
        # Two-phase pop: the in-memory head goes away now so queue snapshots
        # (the UI event below, session_info) stop showing a message whose turn
        # is already on screen — _start_turn blocks until the whole turn
        # finishes, which kept the entry visibly "pending" for the entire
        # drained turn. The durable copy stays until the post-turn ack.
        if not agent.begin_follow_up(queued.id):
            return False
        try:
            await self._runtime.emit_event(
                events.FollowUpQueueUpdatedEvent(
                    session_id=session_id,
                    texts=[item.text for item in agent.follow_up_snapshot()],
                )
            )
            await self._start_turn(session_id, queued.input, turn_id=queued.id)
        except BaseException:
            abort = getattr(agent, "abort_follow_up", None)
            if abort is not None:
                abort(queued.id)
            raise
        if agent.session.headless_completed_turn_id != queued.id:
            completed = Session.load_meta(session_id, work_dir=agent.session.work_dir).headless_completed_turn_id
            if completed != queued.id:
                abort = getattr(agent, "abort_follow_up", None)
                if abort is not None:
                    abort(queued.id)
                return False
            agent.session.headless_completed_turn_id = completed
        next_enqueued_at = time.time() if agent.session.spawn_kind == "headless" else None
        return agent.acknowledge_follow_up(queued.id, next_enqueued_at=next_enqueued_at)

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

    def mark_turn_starting(self, session_id: str, operation_id: str) -> None:
        """Note that a user turn was submitted but its task is not active yet."""
        self._turn_starting[session_id] = operation_id

    def clear_turn_starting(self, session_id: str, operation_id: str) -> None:
        if self._turn_starting.get(session_id) == operation_id:
            self._turn_starting.pop(session_id, None)

    def turn_start_pending(self, session_id: str) -> bool:
        return session_id in self._turn_starting

    def is_queued(self, session_id: str) -> bool:
        return session_id in self._queued_by_id and session_id not in self._running

    def can_replace_queued_for_steer(self, session_id: str) -> bool:
        entry = self._queued_by_id.get(session_id)
        return entry is not None and entry.kind in ("follow_up", "steer")

    def is_running(self, session_id: str) -> bool:
        return session_id in self._running

    def running_session_ids(self) -> set[str]:
        return set(self._running)

    def has_pending(self, session_id: str) -> bool:
        if session_id in self._queued_by_id or session_id in self._steering or self.turn_start_pending(session_id):
            return True
        actor = self._runtime.session_registry.get_session_actor(session_id)
        agent = actor.get_agent() if actor is not None else None
        return bool(agent is not None and agent.peek_next_follow_up())

    def queued_session_ids(self) -> list[str]:
        return [entry.session_id for entry in self._queue]

    async def spawn(self, *, session_id: str, prompt: UserInputPayload, work_dir: Path) -> str:
        """Start a headless run or queue it. Returns "running" or "queued"."""
        entry = QueuedRun(session_id=session_id, queued=QueuedUserInput(input=prompt), work_dir=work_dir)
        await asyncio.to_thread(
            Session.persist_headless_queued_turn,
            session_id,
            work_dir,
            queued_turn=entry.queued,
        )
        self._enqueue(entry)
        self._stopped_sessions.discard(session_id)
        self._pump()
        return "running" if session_id in self._running else "queued"

    async def send(
        self,
        *,
        session_id: str,
        prompt: UserInputPayload,
        work_dir: Path,
    ) -> str:
        """Persist and schedule an idle turn, or append behind existing follow-ups."""
        lock = self._scheduling_locks.setdefault(session_id, asyncio.Lock())
        async with lock:
            # send is the documented retry for a failed session; lift both latches.
            self._stopped_sessions.discard(session_id)
            self.tracker.clear_failed(session_id)
            self._drain_latch_noticed.discard(session_id)
            return await self._send_locked(session_id=session_id, prompt=prompt, work_dir=work_dir)

    async def _send_locked(
        self,
        *,
        session_id: str,
        prompt: UserInputPayload,
        work_dir: Path,
    ) -> str:
        actor = self._runtime.session_registry.get_session_actor(session_id)
        agent = actor.get_agent() if actor is not None else None
        busy = (
            session_id in self._running
            or session_id in self._queued_by_id
            or (actor is not None and not actor.snapshot().is_idle)
        )
        if busy and agent is None and session_id in self._running:
            handoff = self._launch_handoffs.get(session_id)
            if handoff is None:
                raise RuntimeError(f"missing launch handoff for running session {session_id}")
            # A cancelled request must not cancel the launch handoff shared by
            # other requests and the launch task itself.
            agent = await asyncio.shield(handoff)
            actor = self._runtime.session_registry.get_session_actor(session_id)
            registered_agent = actor.get_agent() if actor is not None else None
            if registered_agent is None or registered_agent is not agent:
                raise RuntimeError(f"initialized agent is unavailable for session {session_id}")
        busy = (
            session_id in self._running
            or session_id in self._queued_by_id
            or (actor is not None and not actor.snapshot().is_idle)
        )
        has_follow_ups = agent is not None and agent.peek_next_follow_up() is not None
        session = agent.session if agent is not None else Session.load_meta(session_id, work_dir=work_dir)
        if session.spawn_kind != "headless":
            if busy or has_follow_ups:
                operation_id = await self._runtime.submit(
                    op.FollowUpAgentOperation(session_id=session_id, input=prompt)
                )
                await self._runtime.wait_for(operation_id)
                self._schedule_follow_up_drain(session_id)
                return "queued"
            await self._ensure_agent(session_id, work_dir)
            await self._runtime.emit_event(
                events.UserMessageEvent(content=prompt.text, session_id=session_id, images=prompt.images)
            )
            run = op.RunAgentOperation(session_id=session_id, input=prompt)
            self.mark_turn_starting(session_id, run.id)
            try:
                await self._runtime.submit(run)
            except BaseException:
                self.clear_turn_starting(session_id, run.id)
                raise
            return "started"
        if busy or has_follow_ups:
            operation_id = await self._runtime.submit(op.FollowUpAgentOperation(session_id=session_id, input=prompt))
            await self._runtime.wait_for(operation_id)
            self._schedule_follow_up_drain(session_id)
            return "queued"
        entry = QueuedRun(session_id=session_id, queued=QueuedUserInput(input=prompt), work_dir=work_dir)
        await asyncio.to_thread(
            Session.persist_headless_queued_turn,
            session_id,
            work_dir,
            queued_turn=entry.queued,
        )
        self._enqueue(entry)
        self._pump()
        return "started" if session_id in self._running else "queued"

    async def steer(
        self,
        *,
        session_id: str,
        prompt: UserInputPayload,
        work_dir: Path,
    ) -> str:
        """Schedule a fresh turn without exposing an idle transition."""
        lock = self._scheduling_locks.setdefault(session_id, asyncio.Lock())
        async with lock:
            self._stopped_sessions.discard(session_id)
            self.tracker.clear_failed(session_id)
            self._drain_latch_noticed.discard(session_id)
            actor = self._runtime.session_registry.get_session_actor(session_id)
            agent = actor.get_agent() if actor is not None else None
            session = agent.session if agent is not None else Session.load_meta(session_id, work_dir=work_dir)
            if session.spawn_kind != "headless":
                return await self._steer_interactive(session_id, prompt, work_dir)

            queued = self._queued_by_id.get(session_id)
            if queued is not None:
                if queued.kind == "turn":
                    raise RuntimeError("session already has a fresh turn queued")
                self._queued_by_id.pop(session_id, None)
                with contextlib.suppress(ValueError):
                    self._queue.remove(queued)

            entry = QueuedRun(
                session_id=session_id,
                queued=QueuedUserInput(input=prompt),
                work_dir=work_dir,
                kind="steer",
            )
            self._steering.add(session_id)
            self._enqueue(entry)
            try:
                await asyncio.to_thread(
                    Session.persist_headless_queued_turn,
                    session_id,
                    work_dir,
                    queued_turn=entry.queued,
                )
            except BaseException:
                if self._queued_by_id.get(session_id) is entry:
                    self._queued_by_id.pop(session_id, None)
                    with contextlib.suppress(ValueError):
                        self._queue.remove(entry)
                raise
            finally:
                if self._queued_by_id.get(session_id) is not entry:
                    self._steering.discard(session_id)
                    self._pump()

            try:
                actor = self._runtime.session_registry.get_session_actor(session_id)
                if actor is not None and not actor.snapshot().is_idle:
                    await self._runtime.submit_and_wait(op.InterruptOperation(session_id=session_id))
            finally:
                self._steering.discard(session_id)
                self._pump()
            return "queued" if self._queued_by_id.get(session_id) is entry else "started"

    async def _steer_interactive(
        self,
        session_id: str,
        prompt: UserInputPayload,
        work_dir: Path,
    ) -> str:
        self._steering.add(session_id)
        try:
            actor = self._runtime.session_registry.get_session_actor(session_id)
            if actor is not None and not actor.snapshot().is_idle:
                await self._runtime.submit_and_wait(op.InterruptOperation(session_id=session_id))
            await self._ensure_agent(session_id, work_dir)
            await self._runtime.emit_event(
                events.UserMessageEvent(content=prompt.text, session_id=session_id, images=prompt.images)
            )
            run = op.RunAgentOperation(session_id=session_id, input=prompt)
            self.mark_turn_starting(session_id, run.id)
            try:
                await self._runtime.submit(run)
            except BaseException:
                self.clear_turn_starting(session_id, run.id)
                raise
        finally:
            self._steering.discard(session_id)
        return "started"

    def _enqueue(self, entry: QueuedRun) -> None:
        if entry.session_id in self._queued_by_id:
            return
        self._queue.append(entry)
        self._queued_by_id[entry.session_id] = entry

    async def cancel_queued(self, session_id: str) -> bool:
        lock = self._scheduling_locks.setdefault(session_id, asyncio.Lock())
        async with lock:
            return await self._cancel_queued_locked(session_id)

    async def prepare_interrupt(self, session_id: str, work_dir: Path) -> bool:
        """Cancel pending work and prevent a running launch from pumping it again."""
        lock = self._scheduling_locks.setdefault(session_id, asyncio.Lock())
        async with lock:
            cancelled = await self._cancel_queued_locked(session_id)
            actor = self._runtime.session_registry.get_session_actor(session_id)
            agent = actor.get_agent() if actor is not None else None
            if agent is not None:
                if agent.peek_next_follow_up() is not None:
                    cancelled = True
                agent.pop_all_follow_up()
            elif not cancelled:
                session = Session.load_meta(session_id, work_dir=work_dir)
                if session.follow_up_queue:
                    cancelled = True
                    session.set_follow_up_queue([])
            if session_id in self._running or (actor is not None and not actor.snapshot().is_idle):
                self._stopped_sessions.add(session_id)
            return cancelled

    async def _cancel_queued_locked(self, session_id: str) -> bool:
        entry = self._queued_by_id.pop(session_id, None)
        if entry is None:
            return False
        with contextlib.suppress(ValueError):
            self._queue.remove(entry)
        if entry.kind != "follow_up":
            await asyncio.to_thread(
                Session.persist_headless_queued_turn,
                session_id,
                entry.work_dir,
                expected_turn_id=entry.queued.id,
            )
        else:
            actor = self._runtime.session_registry.get_session_actor(session_id)
            agent = actor.get_agent() if actor is not None else None
            if agent is not None:
                agent.pop_all_follow_up()
            else:
                Session.load_meta(session_id, work_dir=entry.work_dir).set_follow_up_queue([])
        if session_id in self._running:
            self._stopped_sessions.add(session_id)
        return True

    async def _launch(self, entry: QueuedRun) -> None:
        session_id = entry.session_id
        handoff = self._launch_handoffs.get(session_id)
        try:
            await self._ensure_agent(session_id, entry.work_dir)
            if entry.kind == "follow_up":
                await self._run_headless_follow_up(entry)
                return
            await self._start_turn(
                session_id,
                entry.queued.input,
                turn_id=entry.queued.id,
                clear_queued_work_dir=entry.work_dir,
            )
        except asyncio.CancelledError:
            if handoff is not None and not handoff.done():
                handoff.cancel()
            raise
        except Exception as exc:
            if handoff is not None and not handoff.done():
                handoff.set_exception(exc)
            await self._persist_failed(session_id, failed=True)
            raise
        finally:
            if handoff is not None and not handoff.done():
                handoff.set_exception(RuntimeError(f"launch ended before session {session_id} accepted a turn"))
            if self._launch_handoffs.get(session_id) is handoff:
                self._launch_handoffs.pop(session_id, None)
            self._running.discard(session_id)
            actor = self._runtime.session_registry.get_session_actor(session_id)
            agent = actor.get_agent() if actor is not None else None
            queued = agent.peek_next_follow_up_record() if agent is not None else None
            if session_id in self._stopped_sessions or self.tracker.is_failed(session_id):
                queued = None
            if queued is not None:
                self._enqueue(
                    QueuedRun(
                        session_id=session_id,
                        queued=queued,
                        work_dir=entry.work_dir,
                        kind="follow_up",
                    )
                )
            self._pump()

    async def _ensure_agent(self, session_id: str, work_dir: Path) -> Any:
        actor = self._runtime.session_registry.get_session_actor(session_id)
        agent = actor.get_agent() if actor is not None else None
        if agent is None:
            await self._runtime.submit_and_wait(
                op.InitAgentOperation(
                    session_id=session_id,
                    work_dir=work_dir,
                    defer_welcome_context=True,
                    defer_replay=True,
                )
            )
            actor = self._runtime.session_registry.get_session_actor(session_id)
            agent = actor.get_agent() if actor is not None else None
        if agent is None:
            raise RuntimeError(f"failed to initialize headless session {session_id}")
        return agent

    async def _start_turn(
        self,
        session_id: str,
        prompt: UserInputPayload,
        *,
        turn_id: str,
        clear_queued_work_dir: Path | None = None,
    ) -> None:
        await self._persist_failed(session_id, failed=False)
        await self._runtime.emit_event(
            events.UserMessageEvent(content=prompt.text, session_id=session_id, images=prompt.images)
        )
        operation_id = await self._runtime.submit(op.RunAgentOperation(id=turn_id, session_id=session_id, input=prompt))
        actor = self._runtime.session_registry.get_session_actor(session_id)
        agent = actor.get_agent() if actor is not None else None
        if agent is None:
            raise RuntimeError(f"agent disappeared while submitting turn {turn_id}")
        self._complete_launch_handoff(session_id, agent)
        operation_status = await self._runtime.wait_for(operation_id)
        if operation_status in ("failed", "rejected"):
            raise RuntimeError(f"headless turn {operation_status} before completion: {turn_id}")
        actor = self._runtime.session_registry.get_session_actor(session_id)
        agent = actor.get_agent() if actor is not None else None
        if agent is None:
            raise RuntimeError(f"agent disappeared while starting turn {turn_id}")
        await asyncio.shield(agent.session.wait_for_flush())
        if self.tracker.is_failed(session_id):
            raise RuntimeError(f"headless turn failed before completion: {turn_id}")
        completed_persisted = await asyncio.to_thread(
            Session.persist_headless_completed_turn,
            session_id,
            agent.session.work_dir,
            turn_id=turn_id,
        )
        if not completed_persisted:
            raise RuntimeError(f"failed to persist headless turn completion: {turn_id}")
        agent.session.headless_completed_turn_id = turn_id
        if clear_queued_work_dir is not None:
            lock = self._scheduling_locks.setdefault(session_id, asyncio.Lock())
            async with lock:
                await asyncio.to_thread(
                    Session.persist_headless_queued_turn,
                    session_id,
                    clear_queued_work_dir,
                    expected_turn_id=turn_id,
                )

    async def _persist_failed(self, session_id: str, *, failed: bool) -> None:
        actor = self._runtime.session_registry.get_session_actor(session_id)
        agent = actor.get_agent() if actor is not None else None
        if agent is None or agent.session.spawn_kind != "headless":
            return
        work_dir = agent.session.work_dir
        await asyncio.to_thread(Session.persist_headless_failed, session_id, work_dir, failed=failed)

    def _pump(self) -> None:
        if self._closing:
            return
        attempts = len(self._queue)
        while self._queue and len(self._running) < self._max_running and attempts > 0:
            entry = self._queue.popleft()
            attempts -= 1
            if entry.session_id not in self._queued_by_id:
                continue  # cancelled while queued
            if entry.session_id in self._running:
                self._queue.append(entry)
                continue
            if entry.session_id in self._steering:
                self._queue.append(entry)
                continue
            self._queued_by_id.pop(entry.session_id, None)
            # Reserve before creating the task. Otherwise this loop starts the
            # whole queue before any _launch coroutine can update _running.
            self._running.add(entry.session_id)
            handoff = asyncio.get_running_loop().create_future()
            handoff.add_done_callback(self._consume_handoff_exception)
            self._launch_handoffs[entry.session_id] = handoff
            launch_task = asyncio.create_task(self._launch_logged(entry))
            self._watch_tasks.add(launch_task)
            launch_task.add_done_callback(self._watch_tasks.discard)

    @staticmethod
    def _consume_handoff_exception(handoff: asyncio.Future[Any]) -> None:
        """Retrieve unobserved launch failures without changing await behavior."""
        if not handoff.cancelled():
            handoff.exception()

    def _complete_launch_handoff(self, session_id: str, agent: Any) -> None:
        handoff = self._launch_handoffs.get(session_id)
        if handoff is not None and not handoff.done():
            handoff.set_result(agent)

    async def _launch_logged(self, entry: QueuedRun) -> None:
        try:
            await self._launch(entry)
        except Exception as exc:
            log_info(
                f"[headless] queued launch failed session={entry.session_id}: {exc}",
                debug_type=DebugType.EXECUTION,
            )
