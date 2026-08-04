from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from pydantic import ValidationError

from klaude_code.protocol import llm_param, message
from klaude_code.protocol.models import (
    FileChangeSummary,
    FileStatus,
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
    archived: bool
    model_config_name: str | None
    model_thinking: llm_param.Thinking | None
    model_effort: str | None
    prompt_cache_key: str | None
    next_checkpoint_id: int
    follow_up_queue: list[message.QueuedUserInput]
    headless_queued_turn: message.QueuedUserInput | None
    headless_completed_turn_id: str | None
    headless_failed: bool
    name: str | None
    group: str | None
    agent_type: str | None
    spawn_kind: str | None
    approval_policy: str | None
    parent_session_id: str | None
    vanilla: bool


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


def _parse_follow_up_queue(raw: object, *, fallback_enqueued_at: float) -> list[message.QueuedUserInput]:
    inputs: list[message.QueuedUserInput] = []
    if not isinstance(raw, list):
        return inputs
    for item in cast(list[object], raw):
        if not isinstance(item, dict):
            continue
        try:
            if "input" in item:
                inputs.append(message.QueuedUserInput.model_validate(item))
            else:
                # Legacy queues had payloads only. Their cross-session order
                # cannot be recovered exactly, so use session recency once.
                inputs.append(
                    message.QueuedUserInput(
                        input=message.UserInputPayload.model_validate(item),
                        enqueued_at=fallback_enqueued_at,
                    )
                )
        except ValidationError:
            continue
    return inputs


def _parse_user_input(raw: object) -> message.UserInputPayload | None:
    if not isinstance(raw, dict):
        return None
    try:
        return message.UserInputPayload.model_validate(raw)
    except ValidationError:
        return None


def _parse_headless_queued_turn(raw: dict[str, Any], *, fallback_enqueued_at: float) -> message.QueuedUserInput | None:
    queued = raw.get("headless_queued_turn")
    if isinstance(queued, dict):
        try:
            return message.QueuedUserInput.model_validate(queued)
        except ValidationError:
            return None

    # Compatibility for the unshipped WIP format. New writes remove these
    # three keys, so this path can disappear after that format ages out.
    prompt = _parse_user_input(raw.get("headless_queued_prompt"))
    turn_id = _parse_optional_str(raw.get("headless_queued_turn_id"))
    if prompt is None or turn_id is None:
        return None
    queued_at = raw.get("headless_queued_at")
    return message.QueuedUserInput(
        id=turn_id,
        input=prompt,
        enqueued_at=float(queued_at) if isinstance(queued_at, int | float) else fallback_enqueued_at,
    )


def _parse_optional_str(raw: object) -> str | None:
    if isinstance(raw, str) and raw:
        return raw
    return None


def parse_session_meta(raw: dict[str, Any], *, work_dir: Path) -> LoadedSessionMeta:
    """Parse a meta.json dict; unknown keys (e.g. legacy runtime_owner) are ignored."""

    work_dir_str = raw.get("work_dir")
    if not isinstance(work_dir_str, str) or not work_dir_str:
        work_dir_str = str(work_dir)

    model_thinking_raw = raw.get("model_thinking")
    model_thinking = (
        llm_param.Thinking.model_validate(model_thinking_raw) if isinstance(model_thinking_raw, dict) else None
    )
    archived_raw = raw.get("archived")
    archived = archived_raw if isinstance(archived_raw, bool) else False

    raw_model_effort = raw.get("model_effort")
    if raw.get("model_effort_recorded") is True or isinstance(raw_model_effort, str):
        model_effort = raw_model_effort if isinstance(raw_model_effort, str) else None
    else:
        model_effort = model_thinking.reasoning_effort if model_thinking is not None else None

    created_at = float(raw.get("created_at", time.time()))
    updated_at = float(raw.get("updated_at", created_at))
    return LoadedSessionMeta(
        work_dir=Path(work_dir_str),
        sub_agent_state=SubAgentState.model_validate(raw["sub_agent_state"])
        if isinstance(raw.get("sub_agent_state"), dict)
        else None,
        file_tracker=_parse_file_tracker(raw.get("file_tracker")),
        file_change_summary=_parse_file_change_summary(raw.get("file_change_summary")),
        todos=_parse_todos(raw.get("todos")),
        created_at=created_at,
        updated_at=updated_at,
        title=raw.get("title") if isinstance(raw.get("title"), str) else None,
        model_name=raw.get("model_name") if isinstance(raw.get("model_name"), str) else None,
        archived=archived,
        model_config_name=raw.get("model_config_name") if isinstance(raw.get("model_config_name"), str) else None,
        model_thinking=model_thinking,
        model_effort=model_effort,
        prompt_cache_key=raw.get("prompt_cache_key") if isinstance(raw.get("prompt_cache_key"), str) else None,
        next_checkpoint_id=int(raw.get("next_checkpoint_id", 0)),
        follow_up_queue=_parse_follow_up_queue(raw.get("follow_up_queue"), fallback_enqueued_at=updated_at),
        headless_queued_turn=_parse_headless_queued_turn(raw, fallback_enqueued_at=updated_at),
        headless_completed_turn_id=_parse_optional_str(raw.get("headless_completed_turn_id")),
        headless_failed=raw.get("headless_failed") is True,
        name=_parse_optional_str(raw.get("name")),
        group=_parse_optional_str(raw.get("group")),
        agent_type=_parse_optional_str(raw.get("agent_type")),
        spawn_kind=_parse_optional_str(raw.get("spawn_kind")),
        approval_policy=_parse_optional_str(raw.get("approval_policy")),
        parent_session_id=_parse_optional_str(raw.get("parent_session_id")),
        vanilla=bool(raw.get("vanilla", False)),
    )


__all__ = ["LoadedSessionMeta", "parse_session_meta", "read_json_dict"]
