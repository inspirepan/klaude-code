from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, ClassVar, cast

import pytest

from klaude_code.control.user_interaction import PendingUserInteractionRequest
from klaude_code.protocol import message, op, user_interaction
from klaude_code.server.routes import ws

from .conftest import (
    AppEnv,
    collect_events_until,
    consume_ws_handshake,
    extract_text,
    op_frame,
    send_user_message,
    usage,
    wait_for_event,
)


def test_ask_user_question_flow(app_env: AppEnv) -> None:
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
        message.AssistantTextDelta(content="You chose A"),
        message.AssistantMessage(
            parts=[message.TextPart(text="You chose A")],
            stop_reason="stop",
            usage=usage(input_tokens=7, output_tokens=3),
        ),
    )

    session_id = app_env.create_session()
    with app_env.client.websocket_connect(f"/api/sessions/{session_id}/ws") as websocket:
        consume_ws_handshake(websocket)
        send_user_message(websocket, session_id, "ask me")

        interaction_event = wait_for_event(websocket, "user.interaction.request")
        request_id = interaction_event["event"]["request_id"]
        websocket.send_json(
            op_frame(
                op.UserInteractionRespondOperation(
                    session_id=session_id,
                    request_id=request_id,
                    response=user_interaction.UserInteractionResponse(
                        status="submitted",
                        payload=user_interaction.AskUserQuestionResponsePayload(
                            answers=[
                                user_interaction.AskUserQuestionAnswer(
                                    question_id="q1",
                                    selected_option_ids=["q1_o1"],
                                )
                            ]
                        ),
                    ),
                )
            )
        )
        events = collect_events_until(websocket, "task.finish")

    assert extract_text(events) == "You chose A"


def test_send_pending_interaction_snapshots_replays_pending_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    sent_payloads: list[dict[str, Any]] = []
    request = PendingUserInteractionRequest(
        request_id="req-1",
        session_id="session-1",
        source="tool",
        tool_call_id="call-1",
        payload=user_interaction.AskUserQuestionRequestPayload(
            questions=[
                user_interaction.AskUserQuestionQuestion(
                    id="q1",
                    header="Pick",
                    question="Which option?",
                    options=[
                        user_interaction.AskUserQuestionOption(id="q1_o1", label="A", description="choose A"),
                        user_interaction.AskUserQuestionOption(id="q1_o2", label="B", description="choose B"),
                    ],
                )
            ]
        ),
    )

    class FakeWebSocket:
        async def send_json(self, payload: object) -> None:
            sent_payloads.append(cast(dict[str, Any], payload))

    state = SimpleNamespace(
        runtime=SimpleNamespace(
            session_registry=SimpleNamespace(
                get_session_actor=None,
                list_session_actors=lambda: [],
            )
        )
    )

    def _get_session_actor(_session_id: str) -> Any:
        return SimpleNamespace(pending_requests_snapshot=lambda: [request])

    def _get_server_state(_websocket: object) -> Any:
        return state

    state.runtime.session_registry.get_session_actor = _get_session_actor

    monkeypatch.setattr(ws, "get_server_state_from_ws", _get_server_state)

    send_pending = cast(Any, ws)._send_pending_interaction_snapshots
    asyncio.run(send_pending("session-1", cast(Any, FakeWebSocket())))

    assert len(sent_payloads) == 1
    event = sent_payloads[0]
    assert event["event_type"] == "user.interaction.request"
    assert event["session_id"] == "session-1"
    assert event["event"]["request_id"] == "req-1"
    assert event["event"]["source"] == "tool"
    assert event["event"]["tool_call_id"] == "call-1"
    # Envelope serialization drops None fields.
    assert event["event"]["payload"] == request.payload.model_dump(mode="json", exclude_none=True)


def test_session_websocket_replays_pending_snapshots_before_forwarding_events(monkeypatch: pytest.MonkeyPatch) -> None:
    order: list[str] = []
    forward_started = asyncio.Event()
    receive_started = asyncio.Event()

    class FakeWebSocket:
        query_params: ClassVar[dict[str, str]] = {}

        async def accept(self) -> None:
            return None

        async def send_json(self, _payload: object) -> None:
            return None

    async def _forward_events(_session_id: str, _websocket: FakeWebSocket) -> None:
        order.append("forward")
        forward_started.set()
        await receive_started.wait()

    async def _receive_commands(_session_id: str, _websocket: FakeWebSocket, **_kwargs: Any) -> None:
        order.append("receive")
        receive_started.set()
        await forward_started.wait()

    async def _send_pending_interaction_snapshots(_session_id: str, _websocket: FakeWebSocket) -> None:
        order.append("snapshot")

    def _has_session_actor(_session_id: str) -> bool:
        return True

    runtime = SimpleNamespace(session_registry=SimpleNamespace(has_session_actor=_has_session_actor))
    state = SimpleNamespace(
        runtime=runtime, home_dir=Path("/tmp"), tapes=None, code_fingerprint="test", session_live=None
    )

    def _get_server_state(_websocket: object) -> Any:
        return state

    def _resolve_session_work_dir(_index: object, _home_dir: Path, _session_id: str) -> Path:
        return Path("/tmp")

    async def _load_usage_snapshot(_session_id: str, _work_dir: Path, _websocket: object) -> dict[str, Any]:
        return {}

    monkeypatch.setattr(ws, "get_server_state_from_ws", _get_server_state)
    monkeypatch.setattr(ws, "resolve_session_work_dir_fast", _resolve_session_work_dir)
    monkeypatch.setattr(ws, "_load_usage_snapshot", _load_usage_snapshot)
    monkeypatch.setattr(ws, "_send_pending_interaction_snapshots", _send_pending_interaction_snapshots)
    monkeypatch.setattr(ws, "_forward_events", _forward_events)
    monkeypatch.setattr(ws, "_receive_commands", _receive_commands)

    asyncio.run(asyncio.wait_for(ws.session_websocket(cast(Any, FakeWebSocket()), "session-1"), timeout=0.2))

    assert order[0] == "snapshot"
    assert set(order[1:]) == {"forward", "receive"}


def test_websocket_handler_cancels_pending_peer_task(monkeypatch: pytest.MonkeyPatch) -> None:
    cancelled = asyncio.Event()

    class FakeWebSocket:
        query_params: ClassVar[dict[str, str]] = {}

        async def accept(self) -> None:
            return None

        async def send_json(self, _payload: object) -> None:
            return None

    async def _forward_events(_session_id: str, _websocket: FakeWebSocket) -> None:
        return None

    async def _receive_commands(_session_id: str, _websocket: FakeWebSocket, **_kwargs: Any) -> None:
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    def _has_session_actor(_session_id: str) -> bool:
        return True

    runtime = SimpleNamespace(session_registry=SimpleNamespace(has_session_actor=_has_session_actor))
    state = SimpleNamespace(
        runtime=runtime, home_dir=Path("/tmp"), tapes=None, code_fingerprint="test", session_live=None
    )

    def _get_server_state(_websocket: object) -> Any:
        return state

    def _resolve_session_work_dir(_index: object, _home_dir: Path, _session_id: str) -> Path:
        return Path("/tmp")

    async def _load_usage_snapshot(_session_id: str, _work_dir: Path, _websocket: object) -> dict[str, Any]:
        return {}

    monkeypatch.setattr(ws, "get_server_state_from_ws", _get_server_state)
    monkeypatch.setattr(ws, "resolve_session_work_dir_fast", _resolve_session_work_dir)
    monkeypatch.setattr(ws, "_load_usage_snapshot", _load_usage_snapshot)
    monkeypatch.setattr(ws, "_forward_events", _forward_events)
    monkeypatch.setattr(ws, "_receive_commands", _receive_commands)

    asyncio.run(asyncio.wait_for(ws.session_websocket(cast(Any, FakeWebSocket()), "session-1"), timeout=0.2))

    assert cancelled.is_set()


def test_websocket_handler_does_not_hang_on_stubborn_peer_task(monkeypatch: pytest.MonkeyPatch) -> None:
    cancelled = asyncio.Event()
    closed = asyncio.Event()

    class FakeWebSocket:
        query_params: ClassVar[dict[str, str]] = {}

        async def accept(self) -> None:
            return None

        async def send_json(self, _payload: object) -> None:
            return None

        async def close(self) -> None:
            closed.set()

    async def _forward_events(_session_id: str, _websocket: FakeWebSocket) -> None:
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            cancelled.set()
            task = asyncio.current_task()
            assert task is not None
            task.uncancel()
            await asyncio.Future()

    async def _receive_commands(_session_id: str, _websocket: FakeWebSocket, **_kwargs: Any) -> None:
        return None

    def _has_session_actor(_session_id: str) -> bool:
        return True

    runtime = SimpleNamespace(session_registry=SimpleNamespace(has_session_actor=_has_session_actor))
    state = SimpleNamespace(
        runtime=runtime, home_dir=Path("/tmp"), tapes=None, code_fingerprint="test", session_live=None
    )

    def _get_server_state(_websocket: object) -> Any:
        return state

    def _resolve_session_work_dir(_index: object, _home_dir: Path, _session_id: str) -> Path:
        return Path("/tmp")

    async def _load_usage_snapshot(_session_id: str, _work_dir: Path, _websocket: object) -> dict[str, Any]:
        return {}

    monkeypatch.setattr(ws, "get_server_state_from_ws", _get_server_state)
    monkeypatch.setattr(ws, "resolve_session_work_dir_fast", _resolve_session_work_dir)
    monkeypatch.setattr(ws, "_load_usage_snapshot", _load_usage_snapshot)
    monkeypatch.setattr(ws, "_forward_events", _forward_events)
    monkeypatch.setattr(ws, "_receive_commands", _receive_commands)

    asyncio.run(asyncio.wait_for(ws.session_websocket(cast(Any, FakeWebSocket()), "session-1"), timeout=3.0))

    assert cancelled.is_set()
    assert closed.is_set()


def test_websocket_disconnect_cleans_empty_session(monkeypatch: pytest.MonkeyPatch) -> None:
    cleaned_paths: list[Path] = []

    class FakeWebSocket:
        query_params: ClassVar[dict[str, str]] = {}

        async def accept(self) -> None:
            return None

        async def send_json(self, _payload: object) -> None:
            return None

    class _FakeAgentSession:
        def __init__(self) -> None:
            self.messages_count = 0
            self.work_dir = Path("/tmp/work")

    class _FakeActor:
        def __init__(self) -> None:
            self._agent = SimpleNamespace(session=_FakeAgentSession())

        def get_agent(self) -> Any:
            return self._agent

        def snapshot(self) -> Any:
            return SimpleNamespace(is_idle=True)

    actor = _FakeActor()

    async def _forward_events(_session_id: str, _websocket: FakeWebSocket) -> None:
        return None

    async def _receive_commands(_session_id: str, _websocket: FakeWebSocket, **_kwargs: Any) -> None:
        return None

    def _has_session_actor(_session_id: str) -> bool:
        return True

    def _get_session_actor(_session_id: str) -> Any:
        return actor

    async def _close_session(_session_id: str, force: bool = False) -> bool:
        del force
        return True

    runtime = SimpleNamespace(
        session_registry=SimpleNamespace(
            has_session_actor=_has_session_actor,
            get_session_actor=_get_session_actor,
            list_session_actors=lambda: [],
        ),
        close_session=_close_session,
    )
    state = SimpleNamespace(
        runtime=runtime, home_dir=Path("/tmp"), tapes=None, code_fingerprint="test", session_live=None
    )

    def _get_server_state(_websocket: object) -> Any:
        return state

    def _resolve_session_work_dir(_index: object, _home_dir: Path, _session_id: str) -> Path:
        return Path("/tmp/work")

    async def _load_usage_snapshot(_session_id: str, _work_dir: Path, _websocket: object) -> dict[str, Any]:
        return {}

    def _rmtree(path: Path, ignore_errors: bool = False) -> None:
        del ignore_errors
        cleaned_paths.append(path)

    monkeypatch.setattr(ws, "get_server_state_from_ws", _get_server_state)
    monkeypatch.setattr(ws, "resolve_session_work_dir_fast", _resolve_session_work_dir)
    monkeypatch.setattr(ws, "_load_usage_snapshot", _load_usage_snapshot)
    monkeypatch.setattr(ws, "_forward_events", _forward_events)
    monkeypatch.setattr(ws, "_receive_commands", _receive_commands)
    monkeypatch.setattr(ws.shutil, "rmtree", _rmtree)

    asyncio.run(asyncio.wait_for(ws.session_websocket(cast(Any, FakeWebSocket()), "session-1"), timeout=0.2))

    assert len(cleaned_paths) == 1
