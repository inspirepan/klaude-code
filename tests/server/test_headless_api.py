from __future__ import annotations

import json
import time
from typing import Any, cast

import pytest

from klaude_code.protocol import message
from klaude_code.server.headless import HeadlessRuntime
from klaude_code.session.session import Session

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
        if row["state"] == state and (state != "idle" or not row["pending"]):
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
    _enqueue_text_reply(app_env, "second done", delay_s=0.2)
    _enqueue_text_reply(app_env, "third done", delay_s=0.2)
    _enqueue_text_reply(app_env, "fourth done", delay_s=0.2)

    first = _run(app_env, "first task")
    second = _run(app_env, "second task")
    third = _run(app_env, "third task")
    fourth = _run(app_env, "fourth task")
    assert second["state"] == "queued"
    assert third["state"] == "queued"
    assert fourth["state"] == "queued"
    assert {_get_row(app_env, item["session_id"])["state"] for item in (second, third, fourth)} == {"queued"}

    _wait_for_state(app_env, first["session_id"], "idle")
    # _pump must reserve the one slot before creating a launch task. The old
    # implementation started all three queued runs in this transition.
    queued_states = [_get_row(app_env, item["session_id"])["state"] for item in (second, third, fourth)]
    assert queued_states.count("running") == 1
    assert queued_states.count("queued") == 2
    _wait_for_state(app_env, second["session_id"], "idle")
    _wait_for_state(app_env, third["session_id"], "idle")
    _wait_for_state(app_env, fourth["session_id"], "idle")

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


def test_send_idle_headless_session_obeys_global_slot(app_env: AppEnv) -> None:
    _enqueue_text_reply(app_env, "existing done")
    existing = _run(app_env, "existing")
    _wait_for_state(app_env, existing["session_id"], "idle")

    headless = _headless_runtime(app_env)
    headless._max_running = 1  # type: ignore[attr-defined] # pyright: ignore[reportPrivateUsage]
    _enqueue_text_reply(app_env, "blocker done", delay_s=0.5)
    _enqueue_text_reply(app_env, "sent done")
    blocker = _run(app_env, "block the slot")
    _wait_for_state(app_env, blocker["session_id"], "running")

    response = app_env.client.post(
        f"/api/headless/sessions/{existing['session_id']}/send",
        json={"text": "must wait for a slot"},
    )
    assert response.status_code == 200
    assert response.json()["mode"] == "queued"
    row = _get_row(app_env, existing["session_id"])
    assert row["state"] == "queued"
    assert row["pending"] is True

    _wait_for_state(app_env, blocker["session_id"], "idle")
    _wait_for_state(app_env, existing["session_id"], "idle")
    output = app_env.client.get(f"/api/headless/sessions/{existing['session_id']}/output").json()
    assert output["output"] == "sent done"


def test_send_interactive_session_does_not_consume_headless_slot(app_env: AppEnv) -> None:
    headless = _headless_runtime(app_env)
    headless._max_running = 1  # type: ignore[attr-defined] # pyright: ignore[reportPrivateUsage]

    _enqueue_text_reply(app_env, "blocker done", delay_s=0.5)
    blocker = _run(app_env, "block the headless slot")
    _wait_for_state(app_env, blocker["session_id"], "running")

    created = app_env.client.post("/api/sessions", json={"work_dir": str(app_env.work_dir)})
    assert created.status_code == 200
    interactive_id = created.json()["session_id"]
    _enqueue_text_reply(app_env, "interactive done")

    response = app_env.client.post(
        f"/api/headless/sessions/{interactive_id}/send",
        json={"text": "run independently"},
    )

    assert response.status_code == 200
    assert response.json()["mode"] == "started"
    assert interactive_id not in headless.queued_session_ids()
    assert headless.is_running(interactive_id) is False
    _wait_for_state(app_env, interactive_id, "idle")
    _wait_for_state(app_env, blocker["session_id"], "idle")


def test_send_while_running_queues_follow_up(app_env: AppEnv) -> None:
    # A wide running window (2 x 1.0s per stream item) keeps the follow-up
    # send inside the first turn even under parallel test load.
    _enqueue_text_reply(app_env, "slow reply", delay_s=1.0)
    body = _run(app_env, "slow task")
    session_id = body["session_id"]
    _wait_for_state(app_env, session_id, "running")

    _enqueue_text_reply(app_env, "follow-up reply", delay_s=0.3)
    response = app_env.client.post(f"/api/headless/sessions/{session_id}/send", json={"text": "and then"})
    assert response.status_code == 200
    assert response.json()["mode"] == "queued"
    assert response.json()["pending"] is True

    # The server contract keeps pending true across operation teardown and the
    # next turn start. send --wait must not mistake that window for completion.
    deadline = time.time() + 8.0
    output: dict[str, Any] = {}
    while time.time() < deadline:
        row = _get_row(app_env, session_id)
        output = app_env.client.get(f"/api/headless/sessions/{session_id}/output").json()
        if output.get("output") == "follow-up reply":
            break
        assert row["state"] in ("queued", "running") or row["pending"] is True
        time.sleep(0.05)
    assert output["output"] == "follow-up reply"


def test_waiting_input_brief_and_respond(app_env: AppEnv) -> None:
    _enqueue_ask_question(app_env)
    body = _run(app_env, "ask me")
    session_id = body["session_id"]
    _wait_for_state(app_env, session_id, "waiting_input")
    assert _get_row(app_env, session_id)["pending"] is False

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


def test_kill_running_session_cancels_queued_follow_up(app_env: AppEnv) -> None:
    _enqueue_text_reply(app_env, "slow reply", delay_s=0.6)
    body = _run(app_env, "long task")
    session_id = body["session_id"]
    _wait_for_state(app_env, session_id, "running")

    response = app_env.client.post(f"/api/headless/sessions/{session_id}/send", json={"text": "must not run"})
    assert response.status_code == 200
    assert response.json()["mode"] == "queued"

    killed = app_env.client.post(f"/api/headless/sessions/{session_id}/interrupt")
    assert killed.status_code == 200
    assert killed.json()["was"] == "running"
    _wait_for_state(app_env, session_id, "idle")
    time.sleep(0.8)

    row = _get_row(app_env, session_id)
    assert row["state"] == "idle"
    assert row["pending"] is False
    session = Session.load_meta(session_id, work_dir=app_env.work_dir)
    assert session.follow_up_queue == []


def test_steer_starts_fresh_scheduled_turn(app_env: AppEnv) -> None:
    _enqueue_text_reply(app_env, "interrupted", delay_s=1.0)
    body = _run(app_env, "long task")
    session_id = body["session_id"]
    _wait_for_state(app_env, session_id, "running")
    deadline = time.time() + 8.0
    call_count = 0
    while time.time() < deadline:
        actor = app_env.runtime.session_registry.get_session_actor(session_id)
        agent = actor.get_agent() if actor is not None else None
        call_count = getattr(agent.profile.llm_client, "call_count", 0) if agent is not None else 0
        if call_count >= 1:
            break
        time.sleep(0.01)
    assert call_count == 1

    _enqueue_text_reply(app_env, "steered result")
    response = app_env.client.post(
        f"/api/headless/sessions/{session_id}/send",
        json={"text": "change course", "steer": True},
    )
    assert response.status_code == 200
    assert response.json()["mode"] in ("started", "queued")
    row = _get_row(app_env, session_id)
    assert row["state"] in ("queued", "running") or row["pending"] is True

    deadline = time.time() + 8.0
    output: dict[str, Any] = {}
    while time.time() < deadline:
        row = _get_row(app_env, session_id)
        output = app_env.client.get(f"/api/headless/sessions/{session_id}/output").json()
        if row["state"] == "idle" and not output["pending"]:
            break
        assert row["state"] in ("queued", "running") or row["pending"] is True
        time.sleep(0.05)
    assert row["state"] == "idle"
    assert output["pending"] is False
    assert output["output"] == "steered result"


def test_failed_persists_and_clears_when_next_turn_starts(app_env: AppEnv) -> None:
    body = _run(app_env, "this call has no fake response")
    session_id = body["session_id"]
    _wait_for_state(app_env, session_id, "failed")

    meta_path = next((app_env.home_dir / ".klaude" / "projects").glob(f"*/sessions/{session_id}/meta.json"))
    assert json.loads(meta_path.read_text())["headless_failed"] is True

    _enqueue_text_reply(app_env, "recovered")
    response = app_env.client.post(f"/api/headless/sessions/{session_id}/send", json={"text": "retry"})
    assert response.status_code == 200
    _wait_for_state(app_env, session_id, "idle")
    assert "headless_failed" not in json.loads(meta_path.read_text())


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
    assert default["pending"] is False

    last_turn = app_env.client.get(f"/api/headless/sessions/{session_id}/output", params={"turns": 1}).json()
    assert "second question" in last_turn["output"]
    assert "second answer" in last_turn["output"]
    assert "first question" not in last_turn["output"]

    transcript = app_env.client.get(f"/api/headless/sessions/{session_id}/output", params={"transcript": True}).json()
    assert "first question" in transcript["output"]
    assert "second answer" in transcript["output"]
