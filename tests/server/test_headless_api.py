from __future__ import annotations

import json
import time
from typing import Any, cast

import pytest

from klaude_code.protocol import message
from klaude_code.server.headless import HeadlessRuntime

from .conftest import AppEnv, usage


@pytest.fixture(autouse=True)
def _no_title_refresh(monkeypatch: pytest.MonkeyPatch):
    """Session-title generation would consume queued fake LLM responses."""

    async def _skip(**_kwargs: Any) -> None:
        return None

    monkeypatch.setattr("klaude_code.agent.runtime.agent_ops.generate_session_title", _skip)


ASK_ARGS = {
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


def _enqueue_text_reply(app_env: AppEnv, text: str, *, delay_s: float = 0.0) -> None:
    app_env.fake_llm.enqueue(
        message.AssistantTextDelta(content=text),
        message.AssistantMessage(
            parts=[message.TextPart(text=text)],
            stop_reason="stop",
            usage=usage(input_tokens=7, output_tokens=3),
        ),
        delay_s=delay_s,
    )


def _enqueue_ask_question(app_env: AppEnv) -> None:
    app_env.fake_llm.enqueue(
        message.AssistantMessage(
            parts=[
                message.ToolCallPart(
                    call_id="call-1",
                    tool_name="AskUserQuestion",
                    arguments_json=json.dumps(ASK_ARGS, ensure_ascii=False),
                )
            ],
            stop_reason="tool_use",
            usage=usage(input_tokens=11, output_tokens=2),
        )
    )


def _run(app_env: AppEnv, prompt: str = "do the thing", **extra: Any) -> dict[str, Any]:
    payload = {"prompt": prompt, "work_dir": str(app_env.work_dir), **extra}
    response = app_env.client.post("/api/headless/run", json=payload)
    assert response.status_code == 200, response.json()
    return cast(dict[str, Any], response.json())


def _get_row(app_env: AppEnv, target: str) -> dict[str, Any]:
    response = app_env.client.get("/api/headless/sessions", params={"targets": target})
    assert response.status_code == 200, response.json()
    sessions = response.json()["sessions"]
    assert sessions, f"no session for target {target}"
    return cast(dict[str, Any], sessions[0])


def _wait_for_state(app_env: AppEnv, target: str, state: str, *, timeout: float = 8.0) -> dict[str, Any]:
    deadline = time.time() + timeout
    row: dict[str, Any] = {}
    while time.time() < deadline:
        row = _get_row(app_env, target)
        if row["state"] == state:
            return row
        time.sleep(0.05)
    raise AssertionError(f"session {target} did not reach state {state}; last row: {row}")


def _headless_runtime(app_env: AppEnv) -> HeadlessRuntime:
    state = cast(Any, app_env.client.app).state.server_state
    assert state.headless is not None
    return cast(HeadlessRuntime, state.headless)


def test_run_creates_headless_session_and_finishes(app_env: AppEnv) -> None:
    _enqueue_text_reply(app_env, "all done")
    body = _run(app_env, "say done", name="worker", group="team", agent="main")
    session_id = body["session_id"]
    assert body["state"] in ("running", "queued")

    row = _wait_for_state(app_env, session_id, "idle")
    assert row["name"] == "worker"
    assert row["group"] == "team"
    assert row["agent_type"] == "main"
    assert row["spawn_kind"] == "headless"

    # Meta persisted on disk carries the headless fields.
    meta_paths = list((app_env.home_dir / ".klaude" / "projects").glob(f"*/sessions/{session_id}/meta.json"))
    assert len(meta_paths) == 1
    meta = json.loads(meta_paths[0].read_text())
    assert meta["spawn_kind"] == "headless"
    assert meta["name"] == "worker"
    assert meta["group"] == "team"
    assert meta["approval_policy"] == "hold"

    output = app_env.client.get(f"/api/headless/sessions/{session_id}/output").json()
    assert output["output"] == "all done"

    # Name resolves as a target.
    assert _get_row(app_env, "worker")["id"] == session_id


def test_run_rejects_duplicate_name(app_env: AppEnv) -> None:
    _enqueue_text_reply(app_env, "one")
    _run(app_env, "first", name="dup")
    response = app_env.client.post(
        "/api/headless/run",
        json={"prompt": "second", "work_dir": str(app_env.work_dir), "name": "dup"},
    )
    assert response.status_code == 409


def test_run_rejects_unknown_agent_type(app_env: AppEnv) -> None:
    response = app_env.client.post(
        "/api/headless/run",
        json={"prompt": "x", "work_dir": str(app_env.work_dir), "agent": "nope"},
    )
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "agent_types" in detail


def test_run_queues_beyond_max_running(app_env: AppEnv) -> None:
    headless = _headless_runtime(app_env)
    headless._max_running = 1  # type: ignore[attr-defined] # pyright: ignore[reportPrivateUsage]

    _enqueue_text_reply(app_env, "first done", delay_s=0.3)
    _enqueue_text_reply(app_env, "second done")

    first = _run(app_env, "first task")
    second = _run(app_env, "second task")
    assert second["state"] == "queued"
    assert _get_row(app_env, second["session_id"])["state"] == "queued"

    _wait_for_state(app_env, first["session_id"], "idle")
    _wait_for_state(app_env, second["session_id"], "idle")

    output = app_env.client.get(f"/api/headless/sessions/{second['session_id']}/output").json()
    assert output["output"] == "second done"


def test_kill_cancels_queued_session(app_env: AppEnv) -> None:
    headless = _headless_runtime(app_env)
    headless._max_running = 1  # type: ignore[attr-defined] # pyright: ignore[reportPrivateUsage]

    _enqueue_text_reply(app_env, "first done", delay_s=0.3)
    first = _run(app_env, "first task")
    second = _run(app_env, "second task")
    assert second["state"] == "queued"

    response = app_env.client.post(f"/api/headless/sessions/{second['session_id']}/interrupt")
    assert response.json()["was"] == "queued"
    _wait_for_state(app_env, first["session_id"], "idle")
    assert _get_row(app_env, second["session_id"])["state"] == "idle"


def test_send_idle_session_starts_new_turn(app_env: AppEnv) -> None:
    _enqueue_text_reply(app_env, "turn one")
    body = _run(app_env, "start")
    session_id = body["session_id"]
    _wait_for_state(app_env, session_id, "idle")

    _enqueue_text_reply(app_env, "turn two")
    response = app_env.client.post(f"/api/headless/sessions/{session_id}/send", json={"text": "again"})
    assert response.status_code == 200
    assert response.json()["mode"] == "started"

    _wait_for_state(app_env, session_id, "idle")
    output = app_env.client.get(f"/api/headless/sessions/{session_id}/output").json()
    assert output["output"] == "turn two"


def test_send_while_running_queues_follow_up(app_env: AppEnv) -> None:
    # A wide running window (2 x 1.0s per stream item) keeps the follow-up
    # send inside the first turn even under parallel test load.
    _enqueue_text_reply(app_env, "slow reply", delay_s=1.0)
    body = _run(app_env, "slow task")
    session_id = body["session_id"]
    _wait_for_state(app_env, session_id, "running")

    _enqueue_text_reply(app_env, "follow-up reply")
    response = app_env.client.post(f"/api/headless/sessions/{session_id}/send", json={"text": "and then"})
    assert response.status_code == 200
    assert response.json()["mode"] == "queued"

    _wait_for_state(app_env, session_id, "idle")
    output = app_env.client.get(f"/api/headless/sessions/{session_id}/output").json()
    assert output["output"] == "follow-up reply"


def test_waiting_input_brief_and_respond(app_env: AppEnv) -> None:
    _enqueue_ask_question(app_env)
    body = _run(app_env, "ask me")
    session_id = body["session_id"]
    _wait_for_state(app_env, session_id, "waiting_input")

    brief = app_env.client.get(f"/api/headless/sessions/{session_id}/brief").json()
    assert brief["state"] == "waiting_input"
    pending = brief["pending_request"]
    assert pending["type"] == "question"
    assert pending["prompt"] == "Which option?"
    assert [option["label"] for option in pending["options"]] == ["A", "B"]

    # Output appends the pending request too.
    output = app_env.client.get(f"/api/headless/sessions/{session_id}/output").json()
    assert output["pending_request"]["type"] == "question"

    _enqueue_text_reply(app_env, "You chose A")
    response = app_env.client.post(
        f"/api/headless/sessions/{session_id}/respond",
        json={"action": "option", "option": 1},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "submitted"

    _wait_for_state(app_env, session_id, "idle")
    output = app_env.client.get(f"/api/headless/sessions/{session_id}/output").json()
    assert output["output"] == "You chose A"


def test_respond_without_pending_request_conflicts(app_env: AppEnv) -> None:
    _enqueue_text_reply(app_env, "done")
    body = _run(app_env, "no questions")
    _wait_for_state(app_env, body["session_id"], "idle")
    response = app_env.client.post(
        f"/api/headless/sessions/{body['session_id']}/respond",
        json={"action": "option", "option": 1},
    )
    assert response.status_code == 409


def test_approval_deny_auto_answers_questions(app_env: AppEnv) -> None:
    _enqueue_ask_question(app_env)
    _enqueue_text_reply(app_env, "worked around")
    body = _run(app_env, "ask me", approval="deny")
    session_id = body["session_id"]

    row = _wait_for_state(app_env, session_id, "idle")
    assert row["state"] == "idle"
    output = app_env.client.get(f"/api/headless/sessions/{session_id}/output").json()
    assert output["output"] == "worked around"
    assert "pending_request" not in output


def test_kill_interrupts_running_session(app_env: AppEnv) -> None:
    _enqueue_text_reply(app_env, "never finishes", delay_s=1.0)
    body = _run(app_env, "long task")
    session_id = body["session_id"]
    _wait_for_state(app_env, session_id, "running")

    response = app_env.client.post(f"/api/headless/sessions/{session_id}/interrupt")
    assert response.status_code == 200
    _wait_for_state(app_env, session_id, "idle")


def test_ps_group_filter_and_target_resolution(app_env: AppEnv) -> None:
    _enqueue_text_reply(app_env, "a")
    _enqueue_text_reply(app_env, "b")
    first = _run(app_env, "task a", group="fanout", name="alpha")
    second = _run(app_env, "task b")
    _wait_for_state(app_env, first["session_id"], "idle")
    _wait_for_state(app_env, second["session_id"], "idle")

    grouped = app_env.client.get("/api/headless/sessions", params={"group": "fanout"}).json()["sessions"]
    assert [row["id"] for row in grouped] == [first["session_id"]]

    # Unique id prefix resolves.
    prefix = first["session_id"][:8]
    resolved = app_env.client.get("/api/headless/sessions", params={"targets": prefix}).json()["sessions"]
    assert resolved[0]["id"] == first["session_id"]

    # Unknown target 404s.
    missing = app_env.client.get("/api/headless/sessions", params={"targets": "zzzzzzzz"})
    assert missing.status_code == 404


def test_output_turns_and_transcript(app_env: AppEnv) -> None:
    _enqueue_text_reply(app_env, "first answer")
    body = _run(app_env, "first question")
    session_id = body["session_id"]
    _wait_for_state(app_env, session_id, "idle")

    _enqueue_text_reply(app_env, "second answer")
    app_env.client.post(f"/api/headless/sessions/{session_id}/send", json={"text": "second question"})
    _wait_for_state(app_env, session_id, "idle")

    default = app_env.client.get(f"/api/headless/sessions/{session_id}/output").json()
    assert default["output"] == "second answer"

    last_turn = app_env.client.get(f"/api/headless/sessions/{session_id}/output", params={"turns": 1}).json()
    assert "second question" in last_turn["output"]
    assert "second answer" in last_turn["output"]
    assert "first question" not in last_turn["output"]

    transcript = app_env.client.get(f"/api/headless/sessions/{session_id}/output", params={"transcript": True}).json()
    assert "first question" in transcript["output"]
    assert "second answer" in transcript["output"]
