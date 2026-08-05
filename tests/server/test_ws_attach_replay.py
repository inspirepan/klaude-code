"""Attach-mode WS tests: replay splice, dedup, multi-client, server drain.

Attach mode (`?replay=1`) is the TUI's connection: the handshake carries
session_info, a synthesized welcome, the persisted history, the in-flight
tape, and a replay_complete marker; the live stream then continues without
gaps or duplicates (deduplicated by per-session event_seq).
"""

from __future__ import annotations

import time
from typing import Any

from klaude_code.protocol import events as protocol_events
from klaude_code.protocol import message, op
from klaude_code.protocol.version import PROTOCOL_VERSION

from .conftest import AppEnv, op_frame, receive_events, usage


def _attach(app_env: AppEnv, session_id: str, **params: str) -> Any:
    query = "replay=1"
    for key, value in params.items():
        query += f"&{key}={value}"
    return app_env.client.websocket_connect(f"/api/sessions/{session_id}/ws?{query}")


def _consume_attach_handshake(websocket: Any) -> dict[str, Any]:
    """Read frames through replay_complete; return a summary."""
    connection_info = websocket.receive_json()
    assert connection_info["type"] == "connection_info"
    session_info = websocket.receive_json()
    assert session_info["type"] == "session_info"
    usage_snapshot = websocket.receive_json()
    assert usage_snapshot["event_type"] == "usage.snapshot"

    replay_frames: list[dict[str, Any]] = []
    while True:
        frame = websocket.receive_json()
        items = frame if isinstance(frame, list) else [frame]
        done = False
        for item in items:
            if item.get("type") == "replay_complete":
                done = True
                break
            replay_frames.append(item)
        if done:
            break
    return {
        "connection_info": connection_info,
        "session_info": session_info,
        "replay": replay_frames,
    }


def _replay_history_events(handshake: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in handshake["replay"]:
        if item.get("type") == "replay_history":
            result.extend(item["events"])
    return result


def _history_user_messages(app_env: AppEnv, session_id: str) -> list[str]:
    actor = app_env.runtime.session_registry.get_session_actor(session_id)
    assert actor is not None
    agent = actor.get_agent()
    assert agent is not None
    return [
        event.content
        for event in agent.session.get_history_item()
        if isinstance(event, protocol_events.UserMessageEvent)
    ]


def _run_one_turn(app_env: AppEnv, session_id: str, text: str, reply: str) -> None:
    app_env.fake_llm.enqueue(
        message.AssistantTextDelta(content=reply),
        message.AssistantMessage(parts=[message.TextPart(text=reply)], stop_reason="stop", usage=usage()),
    )
    response = app_env.client.post(f"/api/headless/sessions/{session_id}/send", json={"text": text})
    assert response.status_code == 200
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        brief = app_env.client.get(f"/api/headless/sessions/{session_id}/brief").json()
        if brief["state"] == "idle":
            return
        time.sleep(0.05)
    raise AssertionError("turn did not finish in time")


def test_attach_idle_session_replays_history(app_env: AppEnv) -> None:
    session_id = app_env.create_session()
    _run_one_turn(app_env, session_id, "hello there", "hi back")

    with _attach(app_env, session_id) as websocket:
        handshake = _consume_attach_handshake(websocket)

    assert handshake["connection_info"]["can_input"] is True
    assert handshake["connection_info"]["protocol_version"] == PROTOCOL_VERSION
    assert handshake["session_info"]["state"] == "idle"

    welcome = [item for item in handshake["replay"] if item.get("event_type") == "welcome"]
    assert len(welcome) == 1

    history_types = [event["event_type"] for event in _replay_history_events(handshake)]
    assert "user.message" in history_types
    assert "task.finish" in history_types


def test_attach_mid_turn_has_no_gap_and_no_duplicates(app_env: AppEnv) -> None:
    session_id = app_env.create_session()
    app_env.fake_llm.enqueue(
        message.AssistantTextDelta(content="chunk-a "),
        message.AssistantTextDelta(
            content="chunk-b ",
        ),
        message.AssistantTextDelta(content="chunk-c"),
        message.AssistantMessage(
            parts=[message.TextPart(text="chunk-a chunk-b chunk-c")], stop_reason="stop", usage=usage()
        ),
        delay_s=0.3,
    )
    response = app_env.client.post(
        f"/api/headless/sessions/{session_id}/send",
        json={"text": "slow question"},
    )
    assert response.status_code == 200

    with _attach(app_env, session_id) as websocket:
        handshake = _consume_attach_handshake(websocket)
        live: list[dict[str, Any]] = []
        for _ in range(200):
            batch = False
            for event in receive_events(websocket):
                live.append(event)
                if event.get("event_type") == "task.finish":
                    batch = True
            if batch:
                break

    # The user message must appear exactly once across replay tape + live.
    tape_user = [item for item in handshake["replay"] if item.get("event_type") == "user.message"]
    live_user = [item for item in live if item.get("event_type") == "user.message"]
    assert len(tape_user) + len(live_user) == 1

    # The assistant text reassembles exactly once, with no repeated chunks.
    def _delta_text(items: list[dict[str, Any]]) -> str:
        return "".join(
            str(item["event"].get("content", "")) for item in items if item.get("event_type") == "assistant.text.delta"
        )

    total_text = _delta_text(handshake["replay"]) + _delta_text(live)
    assert total_text == "chunk-a chunk-b chunk-c"


def test_headless_websocket_streams_deltas_through_task_finish(app_env: AppEnv) -> None:
    app_env.fake_llm.enqueue(
        message.AssistantTextDelta(content="headless "),
        message.AssistantTextDelta(content="stream"),
        message.AssistantMessage(parts=[message.TextPart(text="headless stream")], stop_reason="stop", usage=usage()),
        delay_s=0.2,
    )
    response = app_env.client.post(
        "/api/headless/run",
        json={"prompt": "stream a reply", "work_dir": str(app_env.work_dir)},
    )
    assert response.status_code == 200
    session_id = response.json()["session_id"]

    with _attach(app_env, session_id, peek="1") as websocket:
        handshake = _consume_attach_handshake(websocket)
        collected = [item for item in handshake["replay"] if item.get("event_type")]
        for _ in range(200):
            if any(item.get("event_type") == "task.finish" for item in collected):
                break
            collected.extend(receive_events(websocket))

    text = "".join(
        str(item["event"].get("content", ""))
        for item in collected
        if item.get("session_id") == session_id and item.get("event_type") == "assistant.text.delta"
    )
    assert text == "headless stream"
    assert any(item.get("session_id") == session_id and item.get("event_type") == "task.finish" for item in collected)


def test_two_attached_clients_share_stream_and_both_can_send(app_env: AppEnv) -> None:
    session_id = app_env.create_session()

    with _attach(app_env, session_id) as ws1, _attach(app_env, session_id) as ws2:
        _consume_attach_handshake(ws1)
        _consume_attach_handshake(ws2)

        # Client 1 sends via the generic op frame (TUI path).
        app_env.fake_llm.enqueue(
            message.AssistantTextDelta(content="reply-one"),
            message.AssistantMessage(parts=[message.TextPart(text="reply-one")], stop_reason="stop", usage=usage()),
        )
        ws1.send_json({"type": "emit", "event_type": "user.message", "event": {"content": "from client one"}})
        ws1.send_json(
            {
                "type": "op",
                "operation": {
                    "type": "run_agent",
                    "session_id": session_id,
                    "input": {"text": "from client one"},
                },
            }
        )

        def _collect_turn(websocket: Any) -> list[dict[str, Any]]:
            collected: list[dict[str, Any]] = []
            for _ in range(200):
                finished = False
                for event in receive_events(websocket):
                    collected.append(event)
                    if event.get("event_type") == "task.finish":
                        finished = True
                if finished:
                    return collected
            raise AssertionError("turn did not finish")

        events_1 = _collect_turn(ws1)
        events_2 = _collect_turn(ws2)

        # Both clients observed the same narrative for the shared turn.
        for collected in (events_1, events_2):
            types = [event["event_type"] for event in collected]
            assert "user.message" in types
            assert "task.finish" in types

        # Client 2 can also drive the session (no holder arbitration).
        app_env.fake_llm.enqueue(
            message.AssistantTextDelta(content="reply-two"),
            message.AssistantMessage(parts=[message.TextPart(text="reply-two")], stop_reason="stop", usage=usage()),
        )
        ws2.send_json(
            {
                "type": "op",
                "operation": {
                    "type": "run_agent",
                    "session_id": session_id,
                    "input": {"text": "from client two"},
                },
            }
        )
        events_1b = _collect_turn(ws1)
        assert any(event.get("event_type") == "task.finish" for event in events_1b)

    # Two writers, one server: history on disk is consistent and complete.
    assert _history_user_messages(app_env, session_id) == ["from client one", "from client two"]


def test_server_drains_interactive_follow_up_queue(app_env: AppEnv) -> None:
    session_id = app_env.create_session()

    app_env.fake_llm.enqueue(
        message.AssistantTextDelta(content="slow first"),
        message.AssistantMessage(parts=[message.TextPart(text="slow first")], stop_reason="stop", usage=usage()),
        delay_s=0.4,
    )
    # After the first turn the interactive session schedules an LLM title
    # refresh, which races the drained turn for the next queued response;
    # enqueue two more so both get one (order does not matter here).
    app_env.fake_llm.enqueue(
        message.AssistantTextDelta(content="drained second"),
        message.AssistantMessage(parts=[message.TextPart(text="drained second")], stop_reason="stop", usage=usage()),
    )
    app_env.fake_llm.enqueue(
        message.AssistantTextDelta(content="a title"),
        message.AssistantMessage(parts=[message.TextPart(text="a title")], stop_reason="stop", usage=usage()),
    )

    with _attach(app_env, session_id) as websocket:
        _consume_attach_handshake(websocket)
        websocket.send_json(
            {
                "type": "op",
                "operation": {"type": "run_agent", "session_id": session_id, "input": {"text": "first"}},
            }
        )
        # Queue a follow-up while the first turn is streaming; the server
        # (not an in-process TUI runner) must start the second turn.
        websocket.send_json(
            {
                "type": "op",
                "operation": {"type": "follow_up_agent", "session_id": session_id, "input": {"text": "second"}},
            }
        )

        finishes = 0
        queue_updates: list[list[str]] = []
        for _ in range(400):
            for event in receive_events(websocket):
                if event.get("event_type") == "task.finish":
                    finishes += 1
                if event.get("event_type") == "follow.up.queue.updated":
                    queue_updates.append(list(event["event"].get("texts", [])))
            if finishes >= 2 and [] in queue_updates:
                break
        assert finishes >= 2

    # The queue event mirrored the enqueue and the drain.
    assert ["second"] in queue_updates
    assert [] in queue_updates

    assert _history_user_messages(app_env, session_id) == ["first", "second"]


def test_op_frame_rejects_foreign_session(app_env: AppEnv) -> None:
    session_id = app_env.create_session()
    other_id = app_env.create_session()

    with _attach(app_env, session_id) as websocket:
        _consume_attach_handshake(websocket)
        websocket.send_json(
            {
                "type": "op",
                "operation": {"type": "interrupt", "session_id": other_id},
            }
        )
        frame = websocket.receive_json()
        assert frame["type"] == "error"
        assert frame["code"] == "operation_session_mismatch"


def test_peek_connection_cannot_send(app_env: AppEnv) -> None:
    session_id = app_env.create_session()

    with _attach(app_env, session_id, peek="1") as websocket:
        handshake = _consume_attach_handshake(websocket)
        assert handshake["connection_info"]["can_input"] is False
        websocket.send_json(
            op_frame(op.RunAgentOperation(session_id=session_id, input=message.UserInputPayload(text="rejected")))
        )
        frame = websocket.receive_json()
        assert frame["type"] == "error"
        assert frame["code"] == "peek_read_only"


def test_send_steer_interrupts_and_injects(app_env: AppEnv) -> None:
    session_id = app_env.create_session()

    # A wide window (4 x 5s per stream item) keeps the steer request inside
    # the first turn even under parallel test load; the interrupt cancels the
    # stream, so the test never actually waits this long.
    app_env.fake_llm.enqueue(
        message.AssistantTextDelta(content="long running "),
        message.AssistantTextDelta(content="output"),
        message.AssistantMessage(parts=[message.TextPart(text="long running output")], stop_reason="stop"),
        delay_s=5.0,
    )
    app_env.fake_llm.enqueue(
        message.AssistantTextDelta(content="steered reply"),
        message.AssistantMessage(parts=[message.TextPart(text="steered reply")], stop_reason="stop", usage=usage()),
    )

    response = app_env.client.post(
        f"/api/headless/sessions/{session_id}/send",
        json={"text": "long task"},
    )
    assert response.status_code == 200

    steer = app_env.client.post(
        f"/api/headless/sessions/{session_id}/send",
        json={"text": "change course", "steer": True},
    )
    assert steer.status_code == 200
    assert steer.json()["mode"] == "started"

    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        brief = app_env.client.get(f"/api/headless/sessions/{session_id}/brief").json()
        if brief["state"] == "idle":
            break
        time.sleep(0.05)

    output = app_env.client.get(f"/api/headless/sessions/{session_id}/output").json()
    assert output["output"] == "steered reply"


def test_attach_rehydrates_reclaimed_actor(app_env: AppEnv) -> None:
    session_id = app_env.create_session()
    _run_one_turn(app_env, session_id, "before reclaim", "still here")

    # Simulate the 30min idle actor reclaim. The session stays on disk and
    # attach must rehydrate it before replaying persisted history.
    response = app_env.client.put(
        f"/api/sessions/{session_id}/model/config",
        json={"model_name": "fake"},
    )
    assert response.status_code == 200
    assert not app_env.runtime.session_registry.has_session_actor(session_id)

    with _attach(app_env, session_id) as websocket:
        handshake = _consume_attach_handshake(websocket)

    # Content may arrive via synthesized history or via the retained tape
    # (both splice to the same transcript); assert across both sources.
    replay_events = _replay_history_events(handshake) + handshake["replay"]
    contents = [event["event"].get("content") for event in replay_events if event.get("event_type") == "user.message"]
    assert contents == ["before reclaim"]
    texts = "".join(
        str(event["event"].get("content", ""))
        for event in replay_events
        if event.get("event_type") in ("assistant.text.delta", "assistant.text.end")
    )
    assert "still here" in texts


def test_attach_drains_queue_persisted_across_restart(app_env: AppEnv) -> None:
    """A follow-up queued before a restart/reclaim has no live drain trigger
    (restore only covers headless sessions); attaching must resume it."""
    from klaude_code.protocol.message import QueuedUserInput, UserInputPayload
    from klaude_code.session.store_registry import get_store_for_path

    session_id = app_env.create_session()
    _run_one_turn(app_env, session_id, "first turn", "first reply")

    # Simulate the reclaim/restart: actor gone, queue persisted in meta only.
    assert app_env.client.portal is not None
    assert app_env.client.portal.call(app_env.runtime.close_session, session_id)
    queued = QueuedUserInput(input=UserInputPayload(text="queued while away"))
    store = get_store_for_path(app_env.work_dir)
    assert store.update_meta(
        session_id,
        {"follow_up_queue": [queued.model_dump(mode="json")]},
    )

    app_env.fake_llm.enqueue(
        message.AssistantTextDelta(content="drained reply"),
        message.AssistantMessage(
            parts=[message.TextPart(text="drained reply")],
            stop_reason="stop",
            usage=usage(input_tokens=8, output_tokens=3),
        ),
    )

    with _attach(app_env, session_id) as websocket:
        _consume_attach_handshake(websocket)
        events_seen: list[dict[str, Any]] = []
        for _ in range(300):
            frame = websocket.receive_json()
            items = frame if isinstance(frame, list) else [frame]
            events_seen.extend(item for item in items if isinstance(item, dict))
            if any(item.get("event_type") == "task.finish" for item in items if isinstance(item, dict)):
                break
        else:
            raise AssertionError("queued follow-up never ran after attach")

    texts = "".join(
        str(event["event"].get("content", ""))
        for event in events_seen
        if event.get("event_type") == "assistant.text.delta"
    )
    assert "drained reply" in texts
