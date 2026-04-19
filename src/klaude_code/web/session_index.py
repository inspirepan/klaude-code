from __future__ import annotations

import contextlib
import json
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

from klaude_code.protocol.models import SessionOwner

type TodoSummary = dict[str, str]
type FileChangeSummary = dict[str, list[str] | int | dict[str, dict[str, int]]]

def _read_json_dict(path: Path) -> dict[str, Any] | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(raw, dict):
        return None
    return cast(dict[str, Any], raw)

def _iter_meta_files(home: Path) -> list[Path]:
    projects_dir = home / ".klaude" / "projects"
    if not projects_dir.exists():
        return []
    return list(projects_dir.glob("*/sessions/*/meta.json"))

@dataclass(frozen=True)
class SessionSummary:
    id: str
    created_at: float
    updated_at: float
    work_dir: str
    title: str | None
    user_messages: list[str]
    messages_count: int
    model_name: str | None
    session_state: Literal["idle", "running", "waiting_user_input"] | None
    runtime_owner: SessionOwner | None
    runtime_owner_heartbeat_at: float | None
    archived: bool
    todos: list[TodoSummary]
    file_change_summary: FileChangeSummary

def load_session_summary_from_meta(data: dict[str, Any], *, fallback_session_id: str) -> SessionSummary | None:
    if data.get("sub_agent_state") is not None:
        return None
    if data.get("deleted_at") is not None:
        return None

    sid = str(data.get("id", fallback_session_id))
    created_at_raw = data.get("created_at")
    if isinstance(created_at_raw, int | float | str):
        try:
            created_at = float(created_at_raw)
        except ValueError:
            created_at = time.time()
    else:
        created_at = time.time()
    updated_at_raw = data.get("updated_at", created_at)
    if isinstance(updated_at_raw, int | float | str):
        try:
            updated_at = float(updated_at_raw)
        except ValueError:
            updated_at = created_at
    else:
        updated_at = created_at
    title = data.get("title") if isinstance(data.get("title"), str) else None

    user_messages_raw = data.get("user_messages")
    user_messages: list[str] = []
    if isinstance(user_messages_raw, list):
        for user_message in cast(list[Any], user_messages_raw):
            if isinstance(user_message, str):
                user_messages.append(user_message)

    try:
        messages_count = int(data.get("messages_count", -1))
    except (TypeError, ValueError):
        messages_count = -1

    model_name = data.get("model_name") if isinstance(data.get("model_name"), str) else None
    work_dir = str(data.get("work_dir", ""))
    session_state_raw = data.get("session_state")
    session_state: Literal["idle", "running", "waiting_user_input"] | None = None
    if session_state_raw in {"idle", "running", "waiting_user_input"}:
        session_state = cast(Literal["idle", "running", "waiting_user_input"], session_state_raw)
    runtime_owner_raw = data.get("runtime_owner")
    if isinstance(runtime_owner_raw, dict):
        try:
            runtime_owner = SessionOwner.model_validate(runtime_owner_raw)
        except Exception:
            runtime_owner = None
    else:
        runtime_owner = None
    runtime_owner_heartbeat_raw = data.get("runtime_owner_heartbeat_at")
    runtime_owner_heartbeat_at = (
        float(runtime_owner_heartbeat_raw) if isinstance(runtime_owner_heartbeat_raw, int | float) else None
    )
    archived_raw = data.get("archived")
    archived = archived_raw if isinstance(archived_raw, bool) else False

    todos_raw = data.get("todos")
    todos: list[TodoSummary] = []
    if isinstance(todos_raw, list):
        for todo_raw in cast(list[Any], todos_raw):
            if not isinstance(todo_raw, dict):
                continue
            todo_dict = cast(dict[str, Any], todo_raw)
            content = todo_dict.get("content")
            status = todo_dict.get("status")
            if isinstance(content, str) and isinstance(status, str):
                todos.append({"content": content, "status": status})

    file_change_summary_raw = data.get("file_change_summary")
    raw_summary = cast(dict[str, Any], file_change_summary_raw) if isinstance(file_change_summary_raw, dict) else {}
    try:
        diff_lines_added = int(raw_summary.get("diff_lines_added", 0) or 0)
    except (TypeError, ValueError):
        diff_lines_added = 0
    try:
        diff_lines_removed = int(raw_summary.get("diff_lines_removed", 0) or 0)
    except (TypeError, ValueError):
        diff_lines_removed = 0
    created_files_raw = raw_summary.get("created_files")
    edited_files_raw = raw_summary.get("edited_files")
    created_files = (
        [item for item in cast(list[Any], created_files_raw) if isinstance(item, str)]
        if isinstance(created_files_raw, list)
        else []
    )
    edited_files = (
        [item for item in cast(list[Any], edited_files_raw) if isinstance(item, str)]
        if isinstance(edited_files_raw, list)
        else []
    )
    file_diffs_raw = raw_summary.get("file_diffs")
    file_diffs: dict[str, dict[str, int]] = {}
    if isinstance(file_diffs_raw, dict):
        for fpath, fstats in cast(dict[str, Any], file_diffs_raw).items():
            if isinstance(fstats, dict):
                fstats_dict = cast(dict[str, Any], fstats)
                with contextlib.suppress(TypeError, ValueError):
                    file_diffs[fpath] = {
                        "added": int(fstats_dict.get("added", 0) or 0),
                        "removed": int(fstats_dict.get("removed", 0) or 0),
                    }
    file_change_summary: FileChangeSummary = {
        "created_files": created_files,
        "edited_files": edited_files,
        "diff_lines_added": diff_lines_added,
        "diff_lines_removed": diff_lines_removed,
        "file_diffs": file_diffs,
    }

    return SessionSummary(
        id=sid,
        created_at=created_at,
        updated_at=updated_at,
        work_dir=work_dir,
        title=title,
        user_messages=user_messages,
        messages_count=messages_count,
        model_name=model_name,
        session_state=session_state,
        runtime_owner=runtime_owner,
        runtime_owner_heartbeat_at=runtime_owner_heartbeat_at,
        archived=archived,
        todos=todos,
        file_change_summary=file_change_summary,
    )

def group_sessions(summaries: list[SessionSummary]) -> list[dict[str, Any]]:
    groups_by_work_dir: dict[str, list[SessionSummary]] = {}
    ordered = sorted(summaries, key=lambda item: item.updated_at, reverse=True)
    for item in ordered:
        groups_by_work_dir.setdefault(item.work_dir, []).append(item)
    return [
        {
            "work_dir": work_dir,
            "sessions": [
                {
                    "id": session.id,
                    "created_at": session.created_at,
                    "updated_at": session.updated_at,
                    "work_dir": session.work_dir,
                    "title": session.title,
                    "user_messages": session.user_messages,
                    "messages_count": session.messages_count,
                    "model_name": session.model_name,
                    "session_state": session.session_state,
                    "archived": session.archived,
                    "todos": session.todos,
                    "file_change_summary": session.file_change_summary,
                }
                for session in sessions
            ],
        }
        for work_dir, sessions in groups_by_work_dir.items()
    ]

class SessionIndex:
    def __init__(self, *, home: Path) -> None:
        self._home = home
        self._lock = threading.RLock()
        self._sessions_by_id: dict[str, SessionSummary] = {}
        self.reload()

    def reload(self) -> None:
        sessions: dict[str, SessionSummary] = {}
        for meta_path in _iter_meta_files(self._home):
            data = _read_json_dict(meta_path)
            if data is None:
                continue
            summary = load_session_summary_from_meta(data, fallback_session_id=meta_path.parent.name)
            if summary is None:
                continue
            sessions[summary.id] = summary
        with self._lock:
            self._sessions_by_id = sessions

    def list_all(self) -> list[SessionSummary]:
        with self._lock:
            return list(self._sessions_by_id.values())

    def get(self, session_id: str) -> SessionSummary | None:
        with self._lock:
            return self._sessions_by_id.get(session_id)

    def apply_meta(
        self, data: dict[str, Any], *, fallback_session_id: str
    ) -> tuple[SessionSummary | None, SessionSummary | None]:
        next_summary = load_session_summary_from_meta(data, fallback_session_id=fallback_session_id)
        session_id = str(data.get("id", fallback_session_id))
        with self._lock:
            previous = self._sessions_by_id.get(session_id)
            if next_summary is None:
                if previous is not None:
                    del self._sessions_by_id[session_id]
                return previous, None
            self._sessions_by_id[session_id] = next_summary
            return previous, next_summary

    def remove(self, session_id: str) -> SessionSummary | None:
        with self._lock:
            return self._sessions_by_id.pop(session_id, None)

def list_main_sessions(home: Path) -> list[SessionSummary]:
    summaries: list[SessionSummary] = []
    for meta_path in _iter_meta_files(home):
        data = _read_json_dict(meta_path)
        if data is None:
            continue
        summary = load_session_summary_from_meta(data, fallback_session_id=meta_path.parent.name)
        if summary is not None:
            summaries.append(summary)

    summaries.sort(key=lambda item: item.updated_at, reverse=True)
    return summaries

def list_file_running_states(home: Path) -> dict[str, Literal["running", "waiting_user_input"]]:
    """Return session IDs whose on-disk meta records a non-idle state (lightweight scan)."""
    result: dict[str, Literal["running", "waiting_user_input"]] = {}
    for meta_path in _iter_meta_files(home):
        data = _read_json_dict(meta_path)
        if data is None or data.get("deleted_at") is not None or data.get("sub_agent_state") is not None:
            continue
        state = data.get("session_state")
        if state in ("running", "waiting_user_input"):
            sid = str(data.get("id", meta_path.parent.name))
            result[sid] = state
    return result

def read_session_user_messages(home: Path, session_ids: set[str]) -> dict[str, list[str]]:
    """Read user_messages from meta.json for the given session IDs."""
    if not session_ids:
        return {}
    result: dict[str, list[str]] = {}
    for meta_path in _iter_meta_files(home):
        data = _read_json_dict(meta_path)
        if data is None or data.get("deleted_at") is not None:
            continue
        sid = str(data.get("id", meta_path.parent.name))
        if sid not in session_ids:
            continue
        user_messages_raw = data.get("user_messages")
        user_messages: list[str] = []
        if isinstance(user_messages_raw, list):
            for msg in cast(list[Any], user_messages_raw):
                if isinstance(msg, str):
                    user_messages.append(msg)
        result[sid] = user_messages
        if len(result) == len(session_ids):
            break
    return result

def read_session_titles(home: Path, session_ids: set[str]) -> dict[str, str | None]:
    """Read title from meta.json for the given session IDs."""
    if not session_ids:
        return {}
    result: dict[str, str | None] = {}
    for meta_path in _iter_meta_files(home):
        data = _read_json_dict(meta_path)
        if data is None or data.get("deleted_at") is not None:
            continue
        sid = str(data.get("id", meta_path.parent.name))
        if sid not in session_ids:
            continue
        result[sid] = data.get("title") if isinstance(data.get("title"), str) else None
        if len(result) == len(session_ids):
            break
    return result

def search_sessions(home: Path, query: str) -> list[SessionSummary]:
    """Search sessions by title, user messages, and work_dir.

    Returns matching sessions sorted by updated_at descending.
    """
    query_lower = query.strip().lower()
    if not query_lower:
        return []

    results: list[SessionSummary] = []
    for meta_path in _iter_meta_files(home):
        data = _read_json_dict(meta_path)
        if data is None:
            continue
        summary = load_session_summary_from_meta(data, fallback_session_id=meta_path.parent.name)
        if summary is None:
            continue

        if _session_matches_query(summary, query_lower):
            results.append(summary)

    results.sort(key=lambda item: item.updated_at, reverse=True)
    return results

def _session_matches_query(summary: SessionSummary, query_lower: str) -> bool:
    if summary.title and query_lower in summary.title.lower():
        return True
    if query_lower in summary.work_dir.lower():
        return True
    return any(query_lower in msg.lower() for msg in summary.user_messages)

def resolve_session_work_dir(home: Path, session_id: str) -> Path | None:
    for meta_path in _iter_meta_files(home):
        data = _read_json_dict(meta_path)
        if data is None:
            continue
        if data.get("deleted_at") is not None:
            continue
        sid = str(data.get("id", meta_path.parent.name))
        if sid != session_id:
            continue
        work_dir = data.get("work_dir")
        if not isinstance(work_dir, str) or not work_dir:
            return None
        return Path(work_dir)
    return None

def soft_delete_session(home: Path, session_id: str) -> bool:
    now = time.time()
    for meta_path in _iter_meta_files(home):
        data = _read_json_dict(meta_path)
        if data is None:
            continue
        sid = str(data.get("id", meta_path.parent.name))
        if sid != session_id:
            continue
        data["deleted_at"] = now
        data["updated_at"] = now
        try:
            tmp_path = meta_path.with_suffix(".json.tmp")
            tmp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp_path.replace(meta_path)
        except OSError:
            return False
        return True
    return False
