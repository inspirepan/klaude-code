"""Tests for sub-agent event forwarding through WebSocket.

Covers the scenario where a WebSocket connects to a session that is currently
executing a sub-agent, and the WebSocket has no in-memory snapshot (e.g. viewing
a TUI-owned session from the web).
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from klaude_code.core.agent import runtime_llm as agent_runtime
from klaude_code.core.agent.runtime_llm import LLMClients
from klaude_code.core.control.event_bus import EventBus, event_publish_context
from klaude_code.core.control.event_relay import EventRelayPublisher, event_relay_socket_path
from klaude_code.core.control.runtime_facade import RuntimeFacade
from klaude_code.protocol import events, message
from klaude_code.session.codec import encode_jsonl_line
from klaude_code.session.session import close_default_store, get_store_for_path
from klaude_code.web.app import create_app
from klaude_code.web.interaction import WebInteractionHandler
from klaude_code.web.live_events import WebLiveEvents, start_web_live_events
from klaude_code.web.routes.ws import _collect_descendant_session_ids  # pyright: ignore[reportPrivateUsage]
from klaude_code.web.state import WebAppState

from .conftest import FakeLLMClient

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_session_meta(
    *,
    work_dir: Path,
    session_id: str,
    session_state: str = "running",
    runtime_kind: str = "tui",
) -> None:
    """Create a session owned by a foreign runtime on disk."""
    store = get_store_for_path(work_dir)
    meta_path = store.paths.meta_file(session_id)
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path.write_text(
        json.dumps(
            {
                "id": session_id,
                "work_dir": str(work_dir),
                "title": None,
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


def _write_history_events(work_dir: Path, session_id: str, items: list[message.HistoryEvent]) -> None:
    """Write history events directly to the session's events.jsonl."""
    store = get_store_for_path(work_dir)
    events_path = store.paths.events_file(session_id)
    events_path.parent.mkdir(parents=True, exist_ok=True)
    with open(events_path, "a", encoding="utf-8") as f:
        for item in items:
            f.write(encode_jsonl_line(item))


def _publish_remote_event(
    socket_path: Path,
    *,
    session_id: str,
    task_id: str | None = None,
    content: str = "from-child",
) -> None:
    """Publish an AssistantTextDeltaEvent through the event relay."""

    async def _send() -> None:
        publisher = EventRelayPublisher(socket_path=socket_path)
        bus = EventBus(publish_hook=publisher.publish)
        try:
            if task_id is not None:
                with event_publish_context(task_id=task_id):
                    await bus.publish(events.AssistantTextDeltaEvent(session_id=session_id, content=content))
            else:
                await bus.publish(events.AssistantTextDeltaEvent(session_id=session_id, content=content))
        finally:
            await publisher.aclose()

    asyncio.run(_send())


# ---------------------------------------------------------------------------
# Unit tests for _collect_descendant_session_ids
# ---------------------------------------------------------------------------


def test_collect_descendant_session_ids_empty(tmp_path: Path, isolated_home: Path) -> None:
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    session_id = "a" * 32
    _write_session_meta(work_dir=work_dir, session_id=session_id)

    result = _collect_descendant_session_ids(session_id, work_dir)
    assert result == set()


def test_collect_descendant_session_ids_one_child(tmp_path: Path, isolated_home: Path) -> None:
    work_dir = tmp_path / "work"
    work_dir.mkdir()

    parent_id = "a" * 32
    child_id = "b" * 32
    _write_session_meta(work_dir=work_dir, session_id=parent_id)
    _write_history_events(
        work_dir,
        parent_id,
        [
            message.SpawnSubAgentEntry(
                session_id=child_id,
                sub_agent_type="general-purpose",
                sub_agent_desc="test child",
            )
        ],
    )

    result = _collect_descendant_session_ids(parent_id, work_dir)
    assert result == {child_id}


def test_collect_descendant_session_ids_nested(tmp_path: Path, isolated_home: Path) -> None:
    work_dir = tmp_path / "work"
    work_dir.mkdir()

    parent_id = "a" * 32
    child_id = "b" * 32
    grandchild_id = "c" * 32

    _write_session_meta(work_dir=work_dir, session_id=parent_id)
    _write_history_events(
        work_dir,
        parent_id,
        [
            message.SpawnSubAgentEntry(
                session_id=child_id,
                sub_agent_type="general-purpose",
                sub_agent_desc="child",
            )
        ],
    )
    # Child session also has a grandchild
    _write_session_meta(work_dir=work_dir, session_id=child_id)
    _write_history_events(
        work_dir,
        child_id,
        [
            message.SpawnSubAgentEntry(
                session_id=grandchild_id,
                sub_agent_type="explore",
                sub_agent_desc="grandchild",
            )
        ],
    )

    result = _collect_descendant_session_ids(parent_id, work_dir)
    assert result == {child_id, grandchild_id}


def test_collect_descendant_session_ids_missing_child_history(tmp_path: Path, isolated_home: Path) -> None:
    """If a child session's history file doesn't exist, it should be in the result but not cause errors."""
    work_dir = tmp_path / "work"
    work_dir.mkdir()

    parent_id = "a" * 32
    child_id = "b" * 32

    _write_session_meta(work_dir=work_dir, session_id=parent_id)
    _write_history_events(
        work_dir,
        parent_id,
        [
            message.SpawnSubAgentEntry(
                session_id=child_id,
                sub_agent_type="general-purpose",
                sub_agent_desc="child without history",
            )
        ],
    )
    # No events.jsonl for child_id

    result = _collect_descendant_session_ids(parent_id, work_dir)
    assert result == {child_id}


# ---------------------------------------------------------------------------
# Integration test: WebSocket forwards child session events
# ---------------------------------------------------------------------------


def test_websocket_forwards_child_session_events_without_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When a WebSocket connects to a TUI-owned session (no in-memory snapshot),
    events from child sessions discovered via SpawnSubAgentEntry should still
    be forwarded.
    """
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
        runtime = RuntimeFacade(event_bus, LLMClients(main=fake_llm, main_model_alias="fake"), runtime_kind="web")
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

    # Set up a foreign (TUI-owned) parent session with a spawned child session
    parent_id = "a" * 32
    child_id = "b" * 32
    _write_session_meta(work_dir=work_dir, session_id=parent_id, session_state="running", runtime_kind="tui")
    _write_history_events(
        work_dir,
        parent_id,
        [
            message.SpawnSubAgentEntry(
                session_id=child_id,
                sub_agent_type="general-purpose",
                sub_agent_desc="sub task",
            )
        ],
    )

    with TestClient(app) as client:
        runtime = holder.get("runtime")
        assert isinstance(runtime, RuntimeFacade)

        # WebSocket connects to the parent session (read-only, no actor, no snapshot)
        with client.websocket_connect(f"/api/sessions/{parent_id}/ws") as websocket:
            connection_info = websocket.receive_json()
            assert connection_info["type"] == "connection_info"
            assert connection_info["is_holder"] is False  # read-only

            usage_snapshot = websocket.receive_json()
            assert usage_snapshot["event_type"] == "usage.snapshot"

            # Publish an event with the CHILD session_id via relay
            _publish_remote_event(
                event_relay_socket_path(home_dir=home_dir),
                session_id=child_id,
                content="child-agent-output",
            )

            # The event should be forwarded because the child session was
            # discovered from SpawnSubAgentEntry in the parent's history
            raw: list[dict[str, Any]] | dict[str, Any] = websocket.receive_json()
            child_event = raw[0] if isinstance(raw, list) else raw
            assert child_event["event_type"] == "assistant.text.delta"
            assert child_event["session_id"] == child_id
            assert child_event["event"]["content"] == "child-agent-output"

        # Verify no actor was created for the foreign session
        assert runtime.session_registry.has_session_actor(parent_id) is False
