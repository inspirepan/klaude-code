from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, cast

from klaude_code.protocol import message

from .conftest import AppEnv, collect_events_until, consume_ws_handshake, send_user_message, usage


def _meta_path(app_env: AppEnv, session_id: str) -> Path:
    matches = list((app_env.home_dir / ".klaude" / "projects").glob(f"*/sessions/{session_id}/meta.json"))
    assert len(matches) == 1
    return matches[0]


def _updated_at(path: Path) -> float:
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    return float(cast(dict[str, Any], raw)["updated_at"])


def test_create_session_and_reject_invalid_work_dir(app_env: AppEnv, tmp_path: Path) -> None:
    session_id = app_env.create_session()
    assert _meta_path(app_env, session_id).exists()
    assert app_env.runtime.session_registry.has_session_actor(session_id)

    response = app_env.client.post("/api/sessions", json={"work_dir": str(tmp_path / "missing")})
    assert response.status_code == 400


def test_non_empty_session_is_kept_after_websocket_disconnect(app_env: AppEnv) -> None:
    app_env.fake_llm.enqueue(
        message.AssistantTextDelta(content="done"),
        message.AssistantMessage(
            parts=[message.TextPart(text="done")],
            stop_reason="stop",
            usage=usage(input_tokens=3, output_tokens=1),
        ),
    )
    session_id = app_env.create_session()

    with app_env.client.websocket_connect(f"/api/sessions/{session_id}/ws") as websocket:
        consume_ws_handshake(websocket)
        send_user_message(websocket, session_id, "hello")
        _ = collect_events_until(websocket, "task.finish")

    assert _meta_path(app_env, session_id).exists()


def test_websocket_rehydrate_does_not_touch_updated_at(app_env: AppEnv) -> None:
    session_id = app_env.create_session()
    meta_path = _meta_path(app_env, session_id)
    initial_updated_at = _updated_at(meta_path)

    with app_env.client.websocket_connect(f"/api/sessions/{session_id}/ws") as websocket:
        consume_ws_handshake(websocket)

    assert _updated_at(meta_path) == initial_updated_at

    app_env.fake_llm.enqueue(
        message.AssistantMessage(
            parts=[message.TextPart(text="ack")],
            stop_reason="stop",
            usage=usage(input_tokens=5, output_tokens=1),
        )
    )
    with app_env.client.websocket_connect(f"/api/sessions/{session_id}/ws") as websocket:
        consume_ws_handshake(websocket)
        send_user_message(websocket, session_id, "hello")
        _ = collect_events_until(websocket, "task.finish")

    deadline = time.monotonic() + 1.0
    while _updated_at(meta_path) <= initial_updated_at and time.monotonic() < deadline:
        time.sleep(0.01)
    assert _updated_at(meta_path) > initial_updated_at
