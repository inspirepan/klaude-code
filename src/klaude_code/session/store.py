from __future__ import annotations

import asyncio
import json
import shutil
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from klaude_code.protocol import llm_param, model
from klaude_code.session.codec import decode_jsonl_line, encode_jsonl_line


@dataclass(frozen=True)
class ProjectPaths:
    project_key: str

    @property
    def base_dir(self) -> Path:
        return Path.home() / ".klaude" / "projects" / self.project_key

    @property
    def sessions_dir(self) -> Path:
        return self.base_dir / "sessions"

    @property
    def exports_dir(self) -> Path:
        return self.base_dir / "exports"

    def session_dir(self, session_id: str) -> Path:
        return self.sessions_dir / session_id

    def events_file(self, session_id: str) -> Path:
        return self.session_dir(session_id) / "events.jsonl"

    def meta_file(self, session_id: str) -> Path:
        return self.session_dir(session_id) / "meta.json"


class _WriterClosedError(RuntimeError):
    pass


@dataclass
class _WriteBatch:
    session_id: str
    event_lines: list[str]
    meta: dict[str, Any]
    done: asyncio.Future[None]


class JsonlSessionWriter:
    def __init__(self, paths: ProjectPaths) -> None:
        self._paths = paths
        self._queue: asyncio.Queue[_WriteBatch | None] = asyncio.Queue()
        self._task: asyncio.Task[None] | None = None
        self._closed = False

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
        with events_path.open("a", encoding="utf-8") as f:
            for line in batch.event_lines:
                f.write(line)
            f.flush()

        meta_path = self._paths.meta_file(batch.session_id)
        tmp_path = meta_path.with_suffix(".json.tmp")
        tmp_path.write_text(json.dumps(batch.meta, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_path.replace(meta_path)

        if not batch.done.done():
            batch.done.set_result(None)


class JsonlSessionStore:
    def __init__(self, *, project_key: str) -> None:
        self._paths = ProjectPaths(project_key=project_key)
        self._writer = JsonlSessionWriter(self._paths)
        self._last_flush: dict[str, asyncio.Future[None]] = {}

    @property
    def paths(self) -> ProjectPaths:
        return self._paths

    def load_meta(self, session_id: str) -> dict[str, Any] | None:
        meta_path = self._paths.meta_file(session_id)
        if not meta_path.exists():
            return None
        try:
            raw = json.loads(meta_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
        return cast(dict[str, Any], raw) if isinstance(raw, dict) else None

    def load_history(self, session_id: str) -> list[model.ConversationItem]:
        events_path = self._paths.events_file(session_id)
        if not events_path.exists():
            return []
        try:
            lines = events_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        items: list[model.ConversationItem] = []
        for line in lines:
            item = decode_jsonl_line(line)
            if item is None:
                continue
            items.append(item)
        return items

    def append_and_flush(
        self, *, session_id: str, items: Sequence[model.ConversationItem], meta: dict[str, Any]
    ) -> None:
        if not items:
            return
        loop = asyncio.get_running_loop()
        done: asyncio.Future[None] = loop.create_future()
        self._last_flush[session_id] = done
        batch = _WriteBatch(
            session_id=session_id,
            event_lines=[encode_jsonl_line(item) for item in items],
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

    def delete_session(self, session_id: str) -> None:
        shutil.rmtree(self._paths.session_dir(session_id), ignore_errors=True)

    async def aclose(self) -> None:
        await self._writer.aclose()


def build_meta_snapshot(
    *,
    session_id: str,
    work_dir: Path,
    sub_agent_state: model.SubAgentState | None,
    file_tracker: dict[str, model.FileStatus],
    todos: list[model.TodoItem],
    created_at: float,
    updated_at: float,
    messages_count: int,
    model_name: str | None,
    model_config_name: str | None,
    model_thinking: llm_param.Thinking | None,
) -> dict[str, Any]:
    return {
        "id": session_id,
        "work_dir": str(work_dir),
        "sub_agent_state": sub_agent_state.model_dump(mode="json") if sub_agent_state else None,
        "file_tracker": {path: status.model_dump(mode="json") for path, status in file_tracker.items()},
        "todos": [todo.model_dump(mode="json", exclude_defaults=True) for todo in todos],
        "created_at": created_at,
        "updated_at": updated_at,
        "messages_count": messages_count,
        "model_name": model_name,
        "model_config_name": model_config_name,
        "model_thinking": model_thinking.model_dump(mode="json", exclude_defaults=True, exclude_none=True)
        if model_thinking
        else None,
    }
