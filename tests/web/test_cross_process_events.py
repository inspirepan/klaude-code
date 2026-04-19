from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from klaude_code.agent.runtime import llm as agent_runtime
from klaude_code.agent.runtime.llm import LLMClients
from klaude_code.app.runtime_facade import RuntimeFacade
from klaude_code.control.event_bus import EventBus
from klaude_code.control.event_relay import EventRelayPublisher, event_relay_socket_path
from klaude_code.protocol import events
from klaude_code.session.store_registry import close_default_store
from klaude_code.web.app import create_app
from klaude_code.web.interaction import WebInteractionHandler
from klaude_code.web.live_events import WebLiveEvents, start_web_live_events
from klaude_code.web.state import WebAppState

from .conftest import FakeLLMClient


def _publish_remote_event(socket_path: Path, session_id: str) -> None:
    async def _send() -> None:
        publisher = EventRelayPublisher(socket_path=socket_path)
        bus = EventBus(publish_hook=publisher.publish)
        try:
            await bus.publish(events.AssistantTextDeltaEvent(session_id=session_id, content="from-tui"))
        finally:
            await publisher.aclose()

    asyncio.run(_send())

def test_websocket_receives_cross_process_events(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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
    holder: dict[str, RuntimeFacade | WebLiveEvents] = {}

    async def _state_initializer() -> WebAppState:
        event_bus = EventBus()
        runtime = RuntimeFacade(event_bus, LLMClients(main=fake_llm, main_model_alias="fake"))
        live_events = await start_web_live_events(event_bus, home_dir=home_dir)
        holder["runtime"] = runtime
        holder["live_events"] = live_events
        return WebAppState(
            runtime=runtime,
            event_bus=event_bus,
            interaction_handler=WebInteractionHandler(),
            work_dir=work_dir,
            home_dir=home_dir,
            event_stream=live_events.stream,
        )

    async def _state_shutdown(state: WebAppState) -> None:
        live_events = holder.get("live_events")
        assert isinstance(live_events, WebLiveEvents)
        await live_events.aclose()
        await state.runtime.stop()
        await close_default_store()

    app = create_app(
        work_dir=work_dir,
        home_dir=home_dir,
        state_initializer=_state_initializer,
        state_shutdown=_state_shutdown,
    )

    with TestClient(app) as client:
        create_response = client.post("/api/sessions", json={"work_dir": str(work_dir)})
        assert create_response.status_code == 200
        session_id = str(create_response.json()["session_id"])

        with client.websocket_connect(f"/api/sessions/{session_id}/ws") as websocket:
            connection_info = websocket.receive_json()
            assert connection_info["type"] == "connection_info"

            usage_snapshot = websocket.receive_json()
            assert usage_snapshot["event_type"] == "usage.snapshot"

            _publish_remote_event(event_relay_socket_path(home_dir=home_dir), session_id)

            raw: list[dict[str, Any]] | dict[str, Any] = websocket.receive_json()
            remote_event = raw[0] if isinstance(raw, list) else raw
            assert remote_event["event_type"] == "assistant.text.delta"
            assert remote_event["session_id"] == session_id
            assert remote_event["event"]["content"] == "from-tui"
