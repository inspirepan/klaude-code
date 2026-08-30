from __future__ import annotations

import asyncio
import json
import threading
import uuid
from _thread import LockType
from collections.abc import Callable, Iterable, Sequence
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from klaude_code.const import ProjectPaths
from klaude_code.protocol import llm_param, message
from klaude_code.protocol.models import (
    FileChangeSummary,
    FileStatus,
    TodoItem,
)
from klaude_code.session.codec import decode_jsonl_line, encode_conversation_item, encode_jsonl_line
from klaude_code.session.history import ScanResult, scan_history

# Meta keys owned by direct update_meta writes: a queued history batch carries
# an older snapshot, so the on-disk value wins when the batch lands.
_RUNTIME_META_KEYS = (
    "follow_up_queue",
    "headless_queued_turn",
    # Read-only compatibility keys for the unshipped WIP format.
    "headless_queued_prompt",
    "headless_queued_turn_id",
    "headless_queued_at",
    "headless_completed_turn_id",
    "headless_failed",
)
_DELETE_WINS_META_KEYS = (
    "follow_up_queue",
    "headless_queued_turn",
    "headless_queued_prompt",
    "headless_queued_turn_id",
    "headless_queued_at",
    "headless_completed_turn_id",
    "headless_failed",
)

type SessionMetaObserver = Callable[[str, dict[str, Any]], None]

_SESSION_META_OBSERVERS: list[SessionMetaObserver] = []
_SESSION_META_OBSERVERS_LOCK = threading.Lock()


def register_session_meta_observer(observer: SessionMetaObserver) -> Callable[[], None]:
    with _SESSION_META_OBSERVERS_LOCK:
        _SESSION_META_OBSERVERS.append(observer)

    def _unregister() -> None:
        with _SESSION_META_OBSERVERS_LOCK, suppress(ValueError):
            _SESSION_META_OBSERVERS.remove(observer)

    return _unregister


def _notify_session_meta_observers(session_id: str, meta: dict[str, Any]) -> None:
    with _SESSION_META_OBSERVERS_LOCK:
        observers = list(_SESSION_META_OBSERVERS)
    for observer in observers:
        observer(session_id, dict(meta))


# Called from the writer thread once a batch reached disk, with the session's
# physical jsonl line count after the flush. The server bridges it onto the
# event loop as a HistoryAppendedEvent (see server/history_bridge.py).
type SessionHistoryObserver = Callable[[str, int], None]

_SESSION_HISTORY_OBSERVERS: list[SessionHistoryObserver] = []
_SESSION_HISTORY_OBSERVERS_LOCK = threading.Lock()


def register_session_history_observer(observer: SessionHistoryObserver) -> Callable[[], None]:
    with _SESSION_HISTORY_OBSERVERS_LOCK:
        _SESSION_HISTORY_OBSERVERS.append(observer)

    def _unregister() -> None:
        with _SESSION_HISTORY_OBSERVERS_LOCK, suppress(ValueError):
            _SESSION_HISTORY_OBSERVERS.remove(observer)

    return _unregister


def _notify_session_history_observers(session_id: str, line_count: int) -> None:
    with _SESSION_HISTORY_OBSERVERS_LOCK:
        observers = list(_SESSION_HISTORY_OBSERVERS)
    for observer in observers:
        observer(session_id, line_count)


def count_file_lines(path: Path) -> int:
    """Count physical lines without decoding them.

    Matches ``enumerate(f)`` over the same file: every written line ends in
    ``\n`` (``encode_jsonl_line``) and json escapes bare CR, so counting
    newline bytes is exact. A truncated tail without a newline still counts.
    """
    total = 0
    last = b"\n"
    try:
        with path.open("rb") as f:
            while chunk := f.read(1 << 20):
                total += chunk.count(b"\n")
                last = chunk[-1:]
    except OSError:
        return 0
    return total if last == b"\n" else total + 1


def _read_json_dict(path: Path) -> dict[str, Any] | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return cast(dict[str, Any], raw) if isinstance(raw, dict) else None


def _write_json_dict_atomic(path: Path, data: dict[str, Any], suffix: str) -> None:
    # Use a per-write temp name to avoid concurrent replace races.
    tmp_path = path.with_name(f"{path.stem}.{uuid.uuid4().hex}.{suffix}.tmp")
    tmp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(path)


class _WriterClosedError(RuntimeError):
    pass


@dataclass
class _WriteBatch:
    session_id: str
    items: Sequence[message.HistoryEvent]
    meta: dict[str, Any]
    done: asyncio.Future[None]


class JsonlSessionWriter:
    def __init__(
        self,
        paths: ProjectPaths,
        *,
        meta_lock: LockType,
        on_history_written: Callable[[str], None] | None = None,
    ) -> None:
        self._paths = paths
        self._meta_lock = meta_lock
        self._on_history_written = on_history_written
        self._queue: asyncio.Queue[_WriteBatch | None] = asyncio.Queue()
        self._task: asyncio.Task[None] | None = None
        self._closed = False
        # session_id -> (events file size, line count) after the last batch, so
        # the per-append count costs one stat instead of a full re-scan.
        self._line_counts: dict[str, tuple[int, int]] = {}

    def ensure_started(self) -> None:
        if self._closed:
            raise _WriterClosedError("writer is closed")
        if self._task is not None:
            return
        loop = asyncio.get_running_loop()
        self._task = loop.create_task(self._run())

    def enqueue(self, batch: _WriteBatch) -> None:
        if self._closed:
            raise _WriterClosedError("writer is closed")
        self.ensure_started()
        self._queue.put_nowait(batch)

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        task = self._task
        if task is None:
            return
        await self._queue.put(None)
        with suppress(asyncio.CancelledError):
            await task
        self._task = None

    async def _run(self) -> None:
        while True:
            msg = await self._queue.get()
            try:
                if msg is None:
                    return
                try:
                    await asyncio.to_thread(self._write_batch_sync, msg)
                except Exception as exc:
                    if not msg.done.done():
                        msg.done.set_exception(exc)
            finally:
                self._queue.task_done()

    def _write_batch_sync(self, batch: _WriteBatch) -> None:
        session_dir = self._paths.session_dir(batch.session_id)
        session_dir.mkdir(parents=True, exist_ok=True)

        events_path = self._paths.events_file(batch.session_id)
        line_count = self._line_count_before_append(batch.session_id, events_path)
        with events_path.open("a", encoding="utf-8") as f:
            for item in batch.items:
                f.write(encode_jsonl_line(item))
            f.flush()
        line_count += len(batch.items)
        self._remember_line_count(batch.session_id, events_path, line_count)
        if self._on_history_written is not None:
            self._on_history_written(batch.session_id)
        _notify_session_history_observers(batch.session_id, line_count)

        meta_path = self._paths.meta_file(batch.session_id)
        with self._meta_lock:
            meta = dict(batch.meta)
            if meta_path.exists():
                current_meta = _read_json_dict(meta_path)
                if current_meta is not None:
                    for key in _RUNTIME_META_KEYS:
                        if key in current_meta:
                            meta[key] = current_meta[key]
                        elif key in _DELETE_WINS_META_KEYS:
                            meta.pop(key, None)
            meta = {k: v for k, v in meta.items() if v is not None}

            _write_json_dict_atomic(meta_path, meta, "w")

        _notify_session_meta_observers(batch.session_id, meta)

        if not batch.done.done():
            batch.done.set_result(None)

    def _line_count_before_append(self, session_id: str, events_path: Path) -> int:
        try:
            size = events_path.stat().st_size
        except OSError:
            return 0
        cached = self._line_counts.get(session_id)
        if cached is not None and cached[0] == size:
            return cached[1]
        return count_file_lines(events_path)

    def _remember_line_count(self, session_id: str, events_path: Path, line_count: int) -> None:
        try:
            self._line_counts[session_id] = (events_path.stat().st_size, line_count)
        except OSError:
            self._line_counts.pop(session_id, None)


@dataclass
class _HistoryCacheEntry:
    mtime_ns: int
    size: int
    # One row per physical jsonl line, in file order: (line_index, item).
    # ``None`` marks a line that failed to decode or carries an unknown type.
    rows: list[tuple[int, message.HistoryEvent | None]]


class JsonlSessionStore:
    def __init__(self, *, project_key: str) -> None:
        self._paths = ProjectPaths(project_key=project_key)
        self._meta_lock = threading.Lock()
        self._writer = JsonlSessionWriter(
            self._paths, meta_lock=self._meta_lock, on_history_written=self._invalidate_history_cache
        )
        self._last_flush: dict[str, asyncio.Future[None]] = {}
        # In-memory cache of decoded history keyed by session_id. Invalidated
        # when the events file's (mtime_ns, size) changes, so repeated loads of
        # an unchanged session avoid re-deserializing the whole jsonl.
        self._history_cache: dict[str, _HistoryCacheEntry] = {}
        # Ledger scan results (per-line statuses) under the same stat stamp, so
        # paging the ledger does not re-scan the whole file per request.
        self._scan_cache: dict[str, tuple[tuple[int, int] | None, ScanResult]] = {}
        self._history_cache_lock = threading.Lock()

    @property
    def paths(self) -> ProjectPaths:
        return self._paths

    def load_meta(self, session_id: str) -> dict[str, Any] | None:
        meta_path = self._paths.meta_file(session_id)
        if not meta_path.exists():
            return None
        return _read_json_dict(meta_path)

    def update_meta(self, session_id: str, updates: dict[str, Any]) -> bool:
        meta_path = self._paths.meta_file(session_id)
        with self._meta_lock:
            if not meta_path.exists():
                return False
            data = _read_json_dict(meta_path)
            if data is None:
                return False
            data.update(updates)
            data = {k: v for k, v in data.items() if v is not None}

            try:
                _write_json_dict_atomic(meta_path, data, "u")
            except OSError:
                return False
            _notify_session_meta_observers(session_id, data)
            return True

    def update_meta_if_queued_id(
        self,
        session_id: str,
        *,
        expected_id: str,
        updates: dict[str, Any],
    ) -> bool:
        meta_path = self._paths.meta_file(session_id)
        with self._meta_lock:
            if not meta_path.exists():
                return False
            data = _read_json_dict(meta_path)
            if data is None:
                return False
            queued = data.get("headless_queued_turn")
            current_id = queued.get("id") if isinstance(queued, dict) else data.get("headless_queued_turn_id")
            if current_id != expected_id:
                return False
            data.update(updates)
            data = {k: v for k, v in data.items() if v is not None}
            try:
                _write_json_dict_atomic(meta_path, data, "u")
            except OSError:
                return False
            _notify_session_meta_observers(session_id, data)
            return True

    def create_meta_if_missing(self, session_id: str, meta: dict[str, Any]) -> bool:
        meta_path = self._paths.meta_file(session_id)
        with self._meta_lock:
            if meta_path.exists():
                return False
            try:
                meta_path.parent.mkdir(parents=True, exist_ok=True)
                _write_json_dict_atomic(meta_path, meta, "c")
            except OSError:
                return False
            _notify_session_meta_observers(session_id, meta)
            return True

    def load_history(self, session_id: str) -> list[message.HistoryEvent]:
        """Return the decoded history, using an mtime/size-keyed cache.

        The cache stores the decoded lines for an unchanged events file so
        repeated loads avoid re-reading and re-deserializing the jsonl. Items
        are deep-copied on the way out so callers may mutate their own copies
        without affecting the cache or other callers (matching the previous
        per-call decode semantics).
        """
        return [item.model_copy(deep=True) for _, item in self._cached_rows(session_id) if item is not None]

    def load_history_lines(self, session_id: str) -> list[tuple[int, message.HistoryEvent | None]]:
        """Return every physical jsonl line with its zero-based line index.

        Undecodable lines (bad JSON, unknown ``type``) yield ``None`` but keep
        their index, so line coordinates stay stable — the ledger and
        ``Session._history_lines`` both count file lines, not decoded items.
        Shares the decode cache with ``load_history``.
        """
        return [
            (line_index, item.model_copy(deep=True) if item is not None else None)
            for line_index, item in self._cached_rows(session_id)
        ]

    def history_line_count(self, session_id: str) -> int:
        """Number of physical lines in the session's events file."""
        return len(self._cached_rows(session_id))

    def encode_history_lines(self, session_id: str, start: int, end: int) -> list[tuple[int, dict[str, Any] | None]]:
        """Re-encode a slice of physical lines to their on-disk JSON shape.

        Round-tripping through the codec (rather than copying the decoded
        models out) keeps datetimes and optional fields byte-identical to what
        ``encode_jsonl_line`` wrote, and skips the deep copy
        ``load_history_lines`` pays for callers that only serialize.
        ``None`` marks a line that failed to decode.
        """
        rows = self._cached_rows(session_id)[start:end]
        return [(line_index, encode_conversation_item(item) if item is not None else None) for line_index, item in rows]

    def scan_history_lines(self, session_id: str) -> ScanResult:
        """Per-line ledger statuses for the whole events file, cached.

        A line's status depends on marker lines that come after it, so the scan
        always covers the whole file and callers slice the result. Cached under
        the same ``(mtime_ns, size)`` stamp as the decoded rows.
        """
        key = self._events_stat_key(session_id)
        with self._history_cache_lock:
            cached = self._scan_cache.get(session_id)
            if cached is not None and cached[0] == key:
                return cached[1]
        result = scan_history(self._cached_rows(session_id))
        with self._history_cache_lock:
            self._scan_cache[session_id] = (key, result)
        return result

    def _events_stat_key(self, session_id: str) -> tuple[int, int] | None:
        try:
            stat = self._paths.events_file(session_id).stat()
        except OSError:
            return None
        return stat.st_mtime_ns, stat.st_size

    def _cached_rows(self, session_id: str) -> list[tuple[int, message.HistoryEvent | None]]:
        events_path = self._paths.events_file(session_id)
        try:
            stat = events_path.stat()
        except OSError:
            self._invalidate_history_cache(session_id)
            return []
        mtime_ns, size = stat.st_mtime_ns, stat.st_size

        with self._history_cache_lock:
            entry = self._history_cache.get(session_id)
            if entry is not None and entry.mtime_ns == mtime_ns and entry.size == size:
                return entry.rows

        rows = list(self._decode_history_lines(events_path))
        with self._history_cache_lock:
            self._history_cache[session_id] = _HistoryCacheEntry(mtime_ns=mtime_ns, size=size, rows=rows)
        return rows

    def iter_history(self, session_id: str) -> Iterable[message.HistoryEvent]:
        events_path = self._paths.events_file(session_id)
        if not events_path.exists():
            return
        for _, item in self._decode_history_lines(events_path):
            if item is not None:
                yield item

    def _decode_history_lines(self, events_path: Path) -> Iterable[tuple[int, message.HistoryEvent | None]]:
        try:
            with events_path.open("r", encoding="utf-8") as f:
                for line_index, line in enumerate(f):
                    yield line_index, decode_jsonl_line(line)
        except OSError:
            return

    def _invalidate_history_cache(self, session_id: str) -> None:
        with self._history_cache_lock:
            self._history_cache.pop(session_id, None)
            self._scan_cache.pop(session_id, None)

    def append_and_flush(self, *, session_id: str, items: Sequence[message.HistoryEvent], meta: dict[str, Any]) -> None:
        if not items:
            return
        loop = asyncio.get_running_loop()
        done: asyncio.Future[None] = loop.create_future()
        self._last_flush[session_id] = done
        batch = _WriteBatch(
            session_id=session_id,
            items=items,
            meta=meta,
            done=done,
        )
        self._writer.enqueue(batch)

    async def wait_for_flush(self, session_id: str) -> None:
        fut = self._last_flush.get(session_id)
        if fut is None:
            return
        await fut

    def iter_meta_files(self) -> Iterable[Path]:
        sessions_dir = self._paths.sessions_dir
        if not sessions_dir.exists():
            return []
        return sessions_dir.glob("*/meta.json")

    async def aclose(self) -> None:
        await self._writer.aclose()
        # Retrieve exceptions from pending flush futures so Python does not
        # log "Future exception was never retrieved" during shutdown.
        for fut in self._last_flush.values():
            if fut.done() and not fut.cancelled():
                with suppress(Exception):
                    fut.exception()
        self._last_flush.clear()


def build_meta_snapshot(
    *,
    session_id: str,
    work_dir: Path,
    title: str | None,
    file_tracker: dict[str, FileStatus],
    file_change_summary: FileChangeSummary,
    todos: list[TodoItem],
    user_messages: list[str],
    created_at: float,
    updated_at: float,
    messages_count: int,
    model_name: str | None,
    archived: bool,
    model_config_name: str | None,
    model_thinking: llm_param.Thinking | None,
    prompt_cache_key: str | None = None,
    follow_up_queue: Sequence[message.QueuedUserInput] = (),
    headless_queued_turn: message.QueuedUserInput | None = None,
    headless_completed_turn_id: str | None = None,
    headless_failed: bool = False,
    model_effort: str | None = None,
    name: str | None = None,
    group: str | None = None,
    agent_type: str | None = None,
    spawn_kind: str | None = None,
    approval_policy: str | None = None,
    parent_session_id: str | None = None,
    vanilla: bool = False,
) -> dict[str, Any]:
    follow_up_queue_payload = [item.model_dump(mode="json", exclude_none=True) for item in follow_up_queue]
    # sub_agent_state is no longer persisted: sub-agent identity lives in
    # parent_session_id/agent_type, display state is rebuilt from the parent's
    # SpawnSubAgentEntry. Legacy metas keep being parsed for read compat.
    snapshot: dict[str, Any] = {
        "id": session_id,
        "work_dir": str(work_dir),
        "title": title,
        "file_tracker": {path: status.model_dump(mode="json") for path, status in file_tracker.items()},
        "file_change_summary": file_change_summary.model_dump(mode="json", exclude_defaults=True),
        "todos": [todo.model_dump(mode="json", exclude_defaults=True) for todo in todos],
        # Cache user messages to avoid scanning events.jsonl during session listing.
        "user_messages": list(user_messages),
        "created_at": created_at,
        "updated_at": updated_at,
        "messages_count": messages_count,
        "model_name": model_name,
        "archived": archived,
        "model_config_name": model_config_name,
        "model_thinking": model_thinking.model_dump(mode="json", exclude_defaults=True, exclude_none=True)
        if model_thinking
        else None,
        "model_effort": model_effort,
        "model_effort_recorded": True,
        "prompt_cache_key": prompt_cache_key,
        "follow_up_queue": follow_up_queue_payload or None,
        "headless_queued_turn": headless_queued_turn.model_dump(mode="json", exclude_none=True)
        if headless_queued_turn is not None
        else None,
        "headless_completed_turn_id": headless_completed_turn_id,
        "headless_failed": headless_failed or None,
        # Headless/multiplexer metadata (set by `klaude run`).
        "name": name,
        "group": group,
        "agent_type": agent_type,
        "spawn_kind": spawn_kind,
        "approval_policy": approval_policy,
        "parent_session_id": parent_session_id,
        "vanilla": vanilla or None,
    }
    return {k: v for k, v in snapshot.items() if v is not None}
