from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast


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
    user_messages: list[str]
    messages_count: int
    model_name: str | None
    session_state: Literal["idle", "running", "waiting_user_input"] | None
    archived: bool


def list_main_sessions(home: Path) -> list[SessionSummary]:
    summaries: list[SessionSummary] = []
    for meta_path in _iter_meta_files(home):
        data = _read_json_dict(meta_path)
        if data is None:
            continue
        if data.get("sub_agent_state") is not None:
            continue
        if data.get("deleted_at") is not None:
            continue

        sid = str(data.get("id", meta_path.parent.name))
        try:
            created_at = float(data.get("created_at", meta_path.stat().st_mtime))
        except (OSError, TypeError, ValueError):
            created_at = time.time()
        try:
            updated_at = float(data.get("updated_at", created_at))
        except (TypeError, ValueError):
            updated_at = created_at

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
        archived_raw = data.get("archived")
        archived = archived_raw if isinstance(archived_raw, bool) else False

        summaries.append(
            SessionSummary(
                id=sid,
                created_at=created_at,
                updated_at=updated_at,
                work_dir=work_dir,
                user_messages=user_messages,
                messages_count=messages_count,
                model_name=model_name,
                session_state=session_state,
                archived=archived,
            )
        )

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
