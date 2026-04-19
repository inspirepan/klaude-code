from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from pydantic import ValidationError

from klaude_code.protocol import llm_param
from klaude_code.protocol.models import (
    FileChangeSummary,
    FileStatus,
    SessionOwner,
    SessionRuntimeState,
    SubAgentState,
    TodoItem,
)


@dataclass(frozen=True)
class LoadedSessionMeta:
    work_dir: Path
    sub_agent_state: SubAgentState | None
    file_tracker: dict[str, FileStatus]
    file_change_summary: FileChangeSummary
    todos: list[TodoItem]
    created_at: float
    updated_at: float
    title: str | None
    model_name: str | None
    session_state: SessionRuntimeState | None
    runtime_owner: SessionOwner | None
    runtime_owner_heartbeat_at: float | None
    archived: bool
    model_config_name: str | None
    model_thinking: llm_param.Thinking | None
    next_checkpoint_id: int


def read_json_dict(path: Path) -> dict[str, Any] | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(raw, dict):
        return None
    return cast(dict[str, Any], raw)


def _parse_file_tracker(raw: object) -> dict[str, FileStatus]:
    file_tracker: dict[str, FileStatus] = {}
    if not isinstance(raw, dict):
        return file_tracker
    for path, payload in cast(dict[object, object], raw).items():
        if not isinstance(path, str) or not isinstance(payload, dict):
            continue
        try:
            file_tracker[path] = FileStatus.model_validate(payload)
        except ValidationError:
            continue
    return file_tracker


def _parse_file_change_summary(raw: object) -> FileChangeSummary:
    if not isinstance(raw, dict):
        return FileChangeSummary()
    try:
        return FileChangeSummary.model_validate(raw)
    except ValidationError:
        return FileChangeSummary()


def _parse_todos(raw: object) -> list[TodoItem]:
    todos: list[TodoItem] = []
    if not isinstance(raw, list):
        return todos
    for item in cast(list[object], raw):
        if not isinstance(item, dict):
            continue
        try:
            todos.append(TodoItem.model_validate(item))
        except ValidationError:
            continue
    return todos


def parse_session_state(raw: object) -> SessionRuntimeState | None:
    if not isinstance(raw, str):
        return None
    try:
        return SessionRuntimeState(raw)
    except ValueError:
        return None


def _parse_runtime_owner(raw: object) -> SessionOwner | None:
    if not isinstance(raw, dict):
        return None
    try:
        return SessionOwner.model_validate(raw)
    except ValidationError:
        return None


def parse_session_meta(raw: dict[str, Any], *, work_dir: Path) -> LoadedSessionMeta:
    work_dir_str = raw.get("work_dir")
    if not isinstance(work_dir_str, str) or not work_dir_str:
        work_dir_str = str(work_dir)

    model_thinking_raw = raw.get("model_thinking")
    model_thinking = (
        llm_param.Thinking.model_validate(model_thinking_raw) if isinstance(model_thinking_raw, dict) else None
    )
    runtime_owner_heartbeat_raw = raw.get("runtime_owner_heartbeat_at")
    archived_raw = raw.get("archived")
    archived = archived_raw if isinstance(archived_raw, bool) else False

    return LoadedSessionMeta(
        work_dir=Path(work_dir_str),
        sub_agent_state=SubAgentState.model_validate(raw["sub_agent_state"])
        if isinstance(raw.get("sub_agent_state"), dict)
        else None,
        file_tracker=_parse_file_tracker(raw.get("file_tracker")),
        file_change_summary=_parse_file_change_summary(raw.get("file_change_summary")),
        todos=_parse_todos(raw.get("todos")),
        created_at=float(raw.get("created_at", time.time())),
        updated_at=float(raw.get("updated_at", float(raw.get("created_at", time.time())))),
        title=raw.get("title") if isinstance(raw.get("title"), str) else None,
        model_name=raw.get("model_name") if isinstance(raw.get("model_name"), str) else None,
        session_state=parse_session_state(raw.get("session_state")),
        runtime_owner=_parse_runtime_owner(raw.get("runtime_owner")),
        runtime_owner_heartbeat_at=float(runtime_owner_heartbeat_raw)
        if isinstance(runtime_owner_heartbeat_raw, int | float)
        else None,
        archived=archived,
        model_config_name=raw.get("model_config_name") if isinstance(raw.get("model_config_name"), str) else None,
        model_thinking=model_thinking,
        next_checkpoint_id=int(raw.get("next_checkpoint_id", 0)),
    )


__all__ = ["LoadedSessionMeta", "parse_session_meta", "parse_session_state", "read_json_dict"]
