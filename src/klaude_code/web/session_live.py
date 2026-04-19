from __future__ import annotations

import asyncio
import json
import threading
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast
from uuid import uuid4

from klaude_code.app.runtime_facade import RuntimeFacade
from klaude_code.protocol.models import SessionRuntimeState
from klaude_code.web.session_access import is_session_read_only_for_runtime
from klaude_code.web.session_index import SessionIndex, SessionSummary


@dataclass(frozen=True)
class SessionStreamEvent:
    type: Literal["session.upsert", "session.deleted"]
    session_id: str
    session: dict[str, Any] | None = None

@dataclass(frozen=True)
class _SessionSubscriber:
    subscriber_id: str
    queue: asyncio.Queue[SessionStreamEvent | None]

class SessionStreamSubscription:
    def __init__(self, *, stream: SessionEventStream, subscriber: _SessionSubscriber) -> None:
        self._stream = stream
        self._subscriber = subscriber

    def __aiter__(self) -> AsyncIterator[SessionStreamEvent]:
        return self._iter_events()

    async def _iter_events(self) -> AsyncIterator[SessionStreamEvent]:
        try:
            while True:
                item = await self._subscriber.queue.get()
                try:
                    if item is None:
                        return
                    yield item
                finally:
                    self._subscriber.queue.task_done()
        finally:
            self._stream.detach(self._subscriber.subscriber_id)

class SessionEventStream:
    def __init__(self, *, subscriber_queue_maxsize: int = 256) -> None:
        self._subscriber_queue_maxsize = subscriber_queue_maxsize
        self._subscribers: dict[str, _SessionSubscriber] = {}
        self._loop: asyncio.AbstractEventLoop | None = None
        self._lock = threading.Lock()

    def attach_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        with self._lock:
            self._loop = loop

    def subscribe(self) -> SessionStreamSubscription:
        subscriber = _SessionSubscriber(
            subscriber_id=uuid4().hex,
            queue=asyncio.Queue(maxsize=self._subscriber_queue_maxsize),
        )
        self._subscribers[subscriber.subscriber_id] = subscriber
        return SessionStreamSubscription(stream=self, subscriber=subscriber)

    def subscriber_count(self) -> int:
        return len(self._subscribers)

    def detach(self, subscriber_id: str) -> None:
        subscriber = self._subscribers.pop(subscriber_id, None)
        if subscriber is None:
            return
        while True:
            try:
                _ = subscriber.queue.get_nowait()
                subscriber.queue.task_done()
            except asyncio.QueueEmpty:
                break
        subscriber.queue.put_nowait(None)

    def publish(self, event: SessionStreamEvent) -> None:
        with self._lock:
            loop = self._loop
        if loop is None:
            return
        loop.call_soon_threadsafe(self._publish_nowait, event)

    def _publish_nowait(self, event: SessionStreamEvent) -> None:
        overflowed: list[str] = []
        for subscriber_id, subscriber in list(self._subscribers.items()):
            try:
                subscriber.queue.put_nowait(event)
            except asyncio.QueueFull:
                overflowed.append(subscriber_id)
        for subscriber_id in overflowed:
            self.detach(subscriber_id)

def _derive_session_state_from_snapshot(snapshot: Any) -> Literal["idle", "running", "waiting_user_input"]:
    if snapshot.pending_request_count > 0:
        return cast(
            Literal["idle", "running", "waiting_user_input"], SessionRuntimeState.WAITING_USER_INPUT.value
        )
    if snapshot.active_root_task is not None or snapshot.child_task_count > 0:
        return cast(Literal["idle", "running", "waiting_user_input"], SessionRuntimeState.RUNNING.value)
    return cast(Literal["idle", "running", "waiting_user_input"], SessionRuntimeState.IDLE.value)

class SessionLiveState:
    def __init__(self, *, home_dir: Path, runtime: RuntimeFacade) -> None:
        self._runtime = runtime
        self._loop: asyncio.AbstractEventLoop | None = None
        self.index = SessionIndex(home=home_dir)
        self.stream = SessionEventStream()

    def attach_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop
        self.stream.attach_loop(loop)

    def list_groups(self) -> list[dict[str, Any]]:
        groups_by_work_dir: dict[str, list[dict[str, Any]]] = {}
        for summary in sorted(self.index.list_all(), key=lambda item: item.updated_at, reverse=True):
            session = self.serialize_summary(summary)
            groups_by_work_dir.setdefault(summary.work_dir, []).append(session)
        return [{"work_dir": work_dir, "sessions": sessions} for work_dir, sessions in groups_by_work_dir.items()]

    def serialize_summary(self, summary: SessionSummary) -> dict[str, Any]:
        runtime_state = self._runtime_session_state(summary.id, summary.session_state)
        return {
            "id": summary.id,
            "created_at": summary.created_at,
            "updated_at": summary.updated_at,
            "work_dir": summary.work_dir,
            "title": summary.title,
            "user_messages": summary.user_messages,
            "messages_count": summary.messages_count,
            "model_name": summary.model_name,
            "session_state": runtime_state,
            "read_only": self._is_session_read_only(summary, runtime_state),
            "archived": summary.archived,
            "todos": summary.todos,
            "file_change_summary": summary.file_change_summary,
        }

    def apply_meta_update(self, session_id: str, meta: dict[str, Any]) -> None:
        if self._loop is None:
            return
        self._loop.call_soon_threadsafe(self._apply_meta_update_now, session_id, dict(meta))

    def _apply_meta_update_now(self, session_id: str, meta: dict[str, Any]) -> None:
        previous, current = self.index.apply_meta(meta, fallback_session_id=session_id)
        if current is None:
            if previous is not None:
                self.stream.publish(SessionStreamEvent(type="session.deleted", session_id=session_id))
            return
        previous_payload = self.serialize_summary(previous) if previous is not None else None
        current_payload = self.serialize_summary(current)
        if previous_payload == current_payload:
            return
        self.stream.publish(SessionStreamEvent(type="session.upsert", session_id=current.id, session=current_payload))

    def apply_deleted(self, session_id: str) -> None:
        if self._loop is None:
            return
        self._loop.call_soon_threadsafe(self._apply_deleted_now, session_id)

    def _apply_deleted_now(self, session_id: str) -> None:
        previous = self.index.remove(session_id)
        if previous is None:
            return
        self.stream.publish(SessionStreamEvent(type="session.deleted", session_id=session_id))

    def _runtime_session_state(
        self,
        session_id: str,
        fallback: Literal["idle", "running", "waiting_user_input"] | None,
    ) -> Literal["idle", "running", "waiting_user_input"]:
        actor = self._runtime.session_registry.get_session_actor(session_id)
        if actor is None:
            return fallback or cast(
                Literal["idle", "running", "waiting_user_input"], SessionRuntimeState.IDLE.value
            )
        snapshot = actor.snapshot()
        return _derive_session_state_from_snapshot(snapshot)

    def _is_session_read_only(
        self,
        summary: SessionSummary,
        session_state: Literal["idle", "running", "waiting_user_input"],
    ) -> bool:
        return is_session_read_only_for_runtime(
            current_runtime_id=self._runtime.runtime_id,
            current_runtime_has_actor=self._runtime.session_registry.has_session_actor(summary.id),
            session_state=session_state,
            runtime_owner=summary.runtime_owner,
            runtime_owner_heartbeat_at=summary.runtime_owner_heartbeat_at,
        )

def format_sse_message(event: SessionStreamEvent) -> str:
    payload = {
        "type": event.type,
        "session_id": event.session_id,
        "session": event.session,
    }
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
