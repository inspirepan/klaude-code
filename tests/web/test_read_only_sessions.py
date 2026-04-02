from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from klaude_code.agent import runtime_llm as agent_runtime
from klaude_code.agent.runtime_llm import LLMClients
from klaude_code.app.runtime_facade import RuntimeFacade
from klaude_code.control.event_bus import EventBus
from klaude_code.protocol import message
from klaude_code.session.session import close_default_store, get_store_for_path
from klaude_code.web.app import create_app
from klaude_code.web.interaction import WebInteractionHandler
from klaude_code.web.state import WebAppState

from .conftest import FakeLLMClient, collect_events_until, consume_ws_handshake, usage


def _write_foreign_session(
    *,
    work_dir: Path,
    session_id: str,
    session_state: str,
    runtime_kind: str = "tui",
) -> None:
    store = get_store_for_path(work_dir)
    meta_path = store.paths.meta_file(session_id)
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path.write_text(
        json.dumps(
            {
                "id": session_id,
                "work_dir": str(work_dir),
                "title": "foreign session",
                "sub_agent_state": None,
                "created_at": 1.0,
                "updated_at": 1.0,
                "user_messages": [],
                "messages_count": 0,
                "model_name": None,
                "session_state": session_state,
                "runtime_owner": {
                    "runtime_id": "foreign-runtime",
                    "runtime_kind": runtime_kind,
                    "pid": 99999,
                },
                "runtime_owner_heartbeat_at": time.time(),
                "archived": False,
                "todos": [],
                "file_change_summary": {
                    "created_files": [],
                    "edited_files": [],
                    "diff_lines_added": 0,
                    "diff_lines_removed": 0,
                    "file_diffs": {},
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


@pytest.fixture
def readonly_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    home_dir = tmp_path / "home"
    home_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HOME", str(home_dir))

    def _patched_home(cls: type[Path]) -> Path:
        del cls
        return home_dir

    def _identity_clone(client: Any) -> Any:
        return client

    monkeypatch.setattr(Path, "home", cast(Any, classmethod(_patched_home)))
    monkeypatch.setattr(agent_runtime, "clone_llm_client", _identity_clone)

    work_dir = tmp_path / "work"
    work_dir.mkdir(parents=True, exist_ok=True)
    fake_llm = FakeLLMClient()
    holder: dict[str, RuntimeFacade] = {}

    async def _state_initializer() -> WebAppState:
        event_bus = EventBus()
        runtime = RuntimeFacade(event_bus, LLMClients(main=fake_llm, main_model_alias="fake"), runtime_kind="web")
        holder["runtime"] = runtime
        return WebAppState(
            runtime=runtime,
            event_bus=event_bus,
            interaction_handler=WebInteractionHandler(),
            work_dir=work_dir,
            home_dir=home_dir,
        )

    async def _state_shutdown(state: WebAppState) -> None:
        await state.runtime.stop()
        await close_default_store()

    app = create_app(
        work_dir=work_dir,
        home_dir=home_dir,
        state_initializer=_state_initializer,
        state_shutdown=_state_shutdown,
    )

    with TestClient(app) as client:
        runtime = holder.get("runtime")
        assert isinstance(runtime, RuntimeFacade)
        yield client, runtime, work_dir, fake_llm


def test_websocket_rejects_commands_for_foreign_running_session(
    readonly_env: tuple[TestClient, RuntimeFacade, Path, FakeLLMClient],
) -> None:
    client, runtime, work_dir, _fake_llm = readonly_env
    session_id = "f" * 32
    _write_foreign_session(work_dir=work_dir, session_id=session_id, session_state="running")

    with client.websocket_connect(f"/api/sessions/{session_id}/ws") as websocket:
        consume_ws_handshake(websocket)

        websocket.send_json({"type": "message", "text": "hello"})
        error = websocket.receive_json()
        assert error["type"] == "error"
        assert error["code"] == "session_read_only"

    assert runtime.session_registry.has_session_actor(session_id) is False


def test_rest_message_rejects_foreign_running_session(
    readonly_env: tuple[TestClient, RuntimeFacade, Path, FakeLLMClient],
) -> None:
    client, _runtime, work_dir, _fake_llm = readonly_env
    session_id = "e" * 32
    _write_foreign_session(work_dir=work_dir, session_id=session_id, session_state="running")

    response = client.post(f"/api/sessions/{session_id}/message", json={"text": "hello"})
    assert response.status_code == 409
    assert "read-only" in response.text


def test_stale_owner_allows_web_takeover(
    readonly_env: tuple[TestClient, RuntimeFacade, Path, FakeLLMClient],
) -> None:
    client, runtime, work_dir, fake_llm = readonly_env
    session_id = "d" * 32
    _write_foreign_session(work_dir=work_dir, session_id=session_id, session_state="running")

    meta_path = get_store_for_path(work_dir).paths.meta_file(session_id)
    raw = json.loads(meta_path.read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    raw["runtime_owner_heartbeat_at"] = time.time() - 60
    meta_path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")

    fake_llm.enqueue(
        message.AssistantMessage(
            parts=[message.TextPart(text="claimed")],
            stop_reason="stop",
            usage=usage(input_tokens=5, output_tokens=1),
        )
    )

    with client.websocket_connect(f"/api/sessions/{session_id}/ws") as websocket:
        consume_ws_handshake(websocket)
        websocket.send_json({"type": "message", "text": "take over"})
        events = collect_events_until(websocket, "task.finish")
        assert not any(event.get("type") == "error" for event in events)

    assert runtime.session_registry.has_session_actor(session_id) is True


def test_foreign_idle_tui_session_stays_read_only(
    readonly_env: tuple[TestClient, RuntimeFacade, Path, FakeLLMClient],
) -> None:
    client, _runtime, work_dir, _fake_llm = readonly_env
    session_id = "c" * 32
    _write_foreign_session(work_dir=work_dir, session_id=session_id, session_state="idle", runtime_kind="tui")

    list_response = client.get("/api/sessions")
    assert list_response.status_code == 200
    listed_session = next(
        session
        for group in list_response.json()["groups"]
        for session in group["sessions"]
        if session["id"] == session_id
    )
    assert listed_session["read_only"] is True

    response = client.post(f"/api/sessions/{session_id}/message", json={"text": "hello"})
    assert response.status_code == 409
    assert "read-only" in response.text

    with client.websocket_connect(f"/api/sessions/{session_id}/ws") as websocket:
        consume_ws_handshake(websocket)
        websocket.send_json({"type": "message", "text": "hello"})
        error = websocket.receive_json()
        assert error["type"] == "error"
        assert error["code"] == "session_read_only"


def test_foreign_idle_web_session_is_not_read_only(
    readonly_env: tuple[TestClient, RuntimeFacade, Path, FakeLLMClient],
) -> None:
    client, _runtime, work_dir, _fake_llm = readonly_env
    session_id = "b" * 32
    _write_foreign_session(work_dir=work_dir, session_id=session_id, session_state="idle", runtime_kind="web")

    list_response = client.get("/api/sessions")
    assert list_response.status_code == 200
    listed_session = next(
        session
        for group in list_response.json()["groups"]
        for session in group["sessions"]
        if session["id"] == session_id
    )
    assert listed_session["read_only"] is False
