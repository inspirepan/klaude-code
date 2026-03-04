from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import pytest

from klaude_code.protocol import message
from klaude_code.session.store import JsonlSessionWriter

from .conftest import AppEnv, collect_events_until, usage


def _meta_path_for_session(app_env: AppEnv, session_id: str) -> Path:
    candidates = list((app_env.home_dir / ".klaude" / "projects").glob(f"*/sessions/{session_id}/meta.json"))
    assert len(candidates) == 1
    return candidates[0]


def _session_state_from_meta(meta_path: Path) -> str | None:
    raw = json.loads(meta_path.read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    state = raw.get("session_state")
    return state if isinstance(state, str) else None


def _wait_until_idle(meta_path: Path, *, timeout_s: float = 2.0) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if _session_state_from_meta(meta_path) == "idle":
            return
        time.sleep(0.01)
    raise AssertionError(f"session_state did not become idle, got: {_session_state_from_meta(meta_path)!r}")


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
