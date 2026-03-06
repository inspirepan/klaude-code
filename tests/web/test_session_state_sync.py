# pyright: reportPrivateUsage=false
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, cast

import pytest

from klaude_code.protocol import message
from klaude_code.session.store import JsonlSessionWriter

from .conftest import AppEnv, collect_events_until, usage


def _meta_path_for_session(app_env: AppEnv, session_id: str) -> Path:
    candidates = list((app_env.home_dir / ".klaude" / "projects").glob(f"*/sessions/{session_id}/meta.json"))
    assert len(candidates) == 1
    return candidates[0]


def _session_state_from_meta(meta_path: Path) -> str | None:
    try:
        raw_obj = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    assert isinstance(raw_obj, dict)
    raw = cast(dict[str, Any], raw_obj)
    state = raw.get("session_state")
    return state if isinstance(state, str) else None


def _wait_until_idle(meta_path: Path, *, timeout_s: float = 2.0) -> None:
    _wait_until_state(meta_path, "idle", timeout_s=timeout_s)


def _wait_until_state(meta_path: Path, expected: str, *, timeout_s: float = 2.0) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if _session_state_from_meta(meta_path) == expected:
            return
        time.sleep(0.01)
    raise AssertionError(f"session_state did not become {expected!r}, got: {_session_state_from_meta(meta_path)!r}")


@pytest.fixture
def slow_session_writer(monkeypatch: pytest.MonkeyPatch) -> None:
    original = JsonlSessionWriter._write_batch_sync

    def _slow_write_batch_sync(self: JsonlSessionWriter, batch: Any) -> None:
        time.sleep(0.2)
        original(self, batch)

    monkeypatch.setattr(JsonlSessionWriter, "_write_batch_sync", _slow_write_batch_sync)


def test_session_state_becomes_idle_after_task_finish(app_env: AppEnv, slow_session_writer: None) -> None:
    app_env.fake_llm.enqueue(
        message.AssistantMessage(
            parts=[message.TextPart(text="done")],
            stop_reason="stop",
            usage=usage(input_tokens=5, output_tokens=1),
        )
    )

    session_id = app_env.create_session()
    meta_path = _meta_path_for_session(app_env, session_id)

    with app_env.client.websocket_connect(f"/api/sessions/{session_id}/ws") as websocket:
        _ = websocket.receive_json()
        websocket.send_json({"type": "message", "text": "hello"})
        _ = collect_events_until(websocket, "task.finish")

    _wait_until_idle(meta_path)


def test_session_state_becomes_idle_after_interrupt(app_env: AppEnv, slow_session_writer: None) -> None:
    app_env.fake_llm.enqueue(
        message.AssistantTextDelta(content="still running"),
        message.AssistantMessage(
            parts=[message.TextPart(text="done")],
            stop_reason="stop",
            usage=usage(input_tokens=6, output_tokens=2),
        ),
        delay_s=2.0,
    )

    session_id = app_env.create_session()
    meta_path = _meta_path_for_session(app_env, session_id)

    with app_env.client.websocket_connect(f"/api/sessions/{session_id}/ws") as websocket:
        _ = websocket.receive_json()
        websocket.send_json({"type": "message", "text": "run then interrupt"})
        _ = collect_events_until(websocket, "task.start")
        websocket.send_json({"type": "interrupt"})
        _ = collect_events_until(websocket, "task.finish")

    _wait_until_idle(meta_path)


def test_session_state_stays_waiting_during_user_interaction(app_env: AppEnv, slow_session_writer: None) -> None:
    ask_args = {
        "questions": [
            {
                "question": "Which option?",
                "header": "Pick",
                "options": [
                    {"label": "A", "description": "choose A"},
                    {"label": "B", "description": "choose B"},
                ],
                "multiSelect": False,
            }
        ]
    }
    app_env.fake_llm.enqueue(
        message.AssistantMessage(
            parts=[
                message.ToolCallPart(
                    call_id="call-1",
                    tool_name="AskUserQuestion",
                    arguments_json=json.dumps(ask_args, ensure_ascii=False),
                )
            ],
            stop_reason="tool_use",
            usage=usage(input_tokens=11, output_tokens=2),
        )
    )
    app_env.fake_llm.enqueue(
        message.AssistantMessage(
            parts=[message.TextPart(text="done")],
            stop_reason="stop",
            usage=usage(input_tokens=7, output_tokens=1),
        )
    )

    session_id = app_env.create_session()
    meta_path = _meta_path_for_session(app_env, session_id)

    with app_env.client.websocket_connect(f"/api/sessions/{session_id}/ws") as websocket:
        _ = websocket.receive_json()
        websocket.send_json({"type": "message", "text": "ask me"})

        request_event = None
        for _ in range(200):
            event = websocket.receive_json()
            if event.get("event_type") == "user.interaction.request":
                request_event = event
                break
        assert request_event is not None
        _wait_until_state(meta_path, "waiting_user_input")

        request_id = request_event["event"]["request_id"]
        websocket.send_json(
            {
                "type": "respond",
                "request_id": request_id,
                "status": "cancelled",
            }
        )
        _ = collect_events_until(websocket, "task.finish")

    _wait_until_idle(meta_path)


def test_ws_init_does_not_override_persisted_running_state(app_env: AppEnv) -> None:
    session_id = app_env.create_session()
    meta_path = _meta_path_for_session(app_env, session_id)
    raw_obj = json.loads(meta_path.read_text(encoding="utf-8"))
    assert isinstance(raw_obj, dict)
    raw = cast(dict[str, Any], raw_obj)
    raw["session_state"] = "running"
    meta_path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")

    with app_env.client.websocket_connect(f"/api/sessions/{session_id}/ws") as websocket:
        snapshot = websocket.receive_json()
        assert snapshot["event_type"] == "usage.snapshot"

    assert _session_state_from_meta(meta_path) == "running"
