from __future__ import annotations

import json
import time
from typing import Any, cast

import pytest

from klaude_code.agent.runtime.agent_ops import _session_model_candidates
from klaude_code.config.config import Config, ModelConfig, ProviderConfig
from klaude_code.prompts.messages import EMPTY_RESPONSE_CONTINUATION_PROMPT, build_stream_error_continuation_prompt
from klaude_code.prompts.sub_agents import FORK_CONTEXT_GENERAL_PROMPT
from klaude_code.protocol import events, llm_param, message, op
from klaude_code.protocol.models import ToolStatus
from klaude_code.protocol.models.session_status import SessionControl
from klaude_code.server.headless import HeadlessRuntime
from klaude_code.server.routes import headless as headless_routes
from klaude_code.server.session_index import load_session_summary_from_meta
from klaude_code.session.session import Session

from .conftest import AppEnv, usage


def test_session_list_loads_background_activity_only_for_returned_rows(
    app_env: AppEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    for _ in range(4):
        app_env.create_session()
    loaded: list[str] = []
    original = headless_routes._add_background_activity

    async def capture(state: Any, row: dict[str, Any]) -> None:
        loaded.append(row["id"])
        await original(state, row)

    monkeypatch.setattr(headless_routes, "_add_background_activity", capture)
    response = app_env.client.get("/api/headless/sessions", params={"limit": 1})
    assert response.status_code == 200
    rows = response.json()["sessions"]
    assert len(rows) == 1 and loaded == [rows[0]["id"]]
    assert rows[0]["background_agent_count"] == 0
    loaded.clear()
    response = app_env.client.get("/api/headless/sessions", params={"state": "working"})
    assert response.json()["sessions"] == []
    assert loaded == []


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
    assert body["state"] == "working"
    assert body["status"]["execution"] in ("running", "queued")

    row = _wait_for_state(app_env, session_id, "idle")
    assert row["name"] == "worker"
    assert row["group"] == "team"
    assert row["agent_type"] == "main"
    assert row["spawn_kind"] == "headless"
    # One prompt plus one reply; the web session list shows this per row.
    assert row["messages_count"] == 2

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


def test_resume_finished_session_never_replays_its_durable_input(app_env: AppEnv) -> None:
    _enqueue_text_reply(app_env, "done once")
    session_id = _run(app_env)["session_id"]
    row = _wait_for_state(app_env, session_id, "idle")
    actor = app_env.runtime.session_registry.get_session_actor(session_id)
    assert actor is not None
    agent = actor.get_agent()
    assert agent is not None
    assert agent.session.headless_queued_turn is None
    assert row["status"]["last_turn"]["result"] == "succeeded"

    for _ in range(2):
        response = app_env.client.post(f"/api/headless/sessions/{session_id}/control", json={"action": "resume"})
        assert response.status_code == 200
        assert response.json()["state"] == "idle"
    time.sleep(0.1)
    assert app_env.fake_llm.call_count == 1


@pytest.mark.parametrize("loaded", [False, True], ids=["cold", "live"])
def test_kill_restarted_paused_input_never_replays_on_resume(app_env: AppEnv, loaded: bool) -> None:
    headless = _headless_runtime(app_env)
    assert app_env.client.portal is not None

    async def restore() -> str:
        session = Session.create(work_dir=app_env.work_dir)
        session.spawn_kind = "headless"
        session.ensure_meta_exists()
        queued = message.QueuedUserInput(input=message.UserInputPayload(text="must not execute again"))
        Session.persist_headless_queued_turn(session.id, app_env.work_dir, queued_turn=queued)
        session.begin_turn(queued.id)
        session.set_follow_up_queue([message.QueuedUserInput(input=message.UserInputPayload(text="also cancel"))])
        summary = load_session_summary_from_meta(
            {"id": session.id, "work_dir": str(app_env.work_dir), "spawn_kind": "headless"},
            fallback_session_id=session.id,
        )
        assert summary is not None
        headless.restore([summary])
        if loaded:
            await headless._ensure_agent(session.id, app_env.work_dir)
        return session.id

    session_id = app_env.client.portal.call(restore)
    assert _get_row(app_env, session_id)["state"] == "needs_you"
    killed = app_env.client.post(f"/api/headless/sessions/{session_id}/interrupt")
    assert killed.status_code == 200
    assert killed.json()["was"] == "queued"
    persisted = Session.load_meta(session_id, app_env.work_dir)
    assert persisted.headless_queued_turn is None
    assert persisted.follow_up_queue == []
    actor = app_env.runtime.session_registry.get_session_actor(session_id)
    if actor is not None:
        agent = actor.get_agent()
        assert agent is not None and agent.session.headless_queued_turn is None
    _enqueue_text_reply(app_env, "must not run")
    resumed = app_env.client.post(f"/api/headless/sessions/{session_id}/control", json={"action": "resume"})
    assert resumed.status_code == 200
    assert resumed.json()["state"] == "idle"
    time.sleep(0.1)
    assert app_env.fake_llm.call_count == 0


def test_paused_peer_queue_keeps_needs_you_after_actor_reclaim(
    app_env: AppEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    session_id = app_env.create_session()
    assert app_env.client.portal is not None

    async def pause() -> None:
        actor = app_env.runtime.session_registry.get_session_actor(session_id)
        assert actor is not None
        agent = actor.get_agent()
        assert agent is not None
        agent.session.runtime.control = SessionControl(paused=True, reason="user_interrupt")
        agent.session.persist_runtime()

    app_env.client.portal.call(pause)
    sent = app_env.client.post(f"/api/headless/sessions/{session_id}/send", json={"text": "peer stays queued"})
    assert sent.status_code == 200
    before = _get_row(app_env, session_id)
    assert before["state"] == "needs_you"
    app_env.create_session()

    async def reclaim() -> list[str]:
        return await app_env.runtime.reclaim_idle_sessions(idle_for_seconds=0)

    reclaimed = app_env.client.portal.call(reclaim)
    assert session_id in reclaimed
    assert app_env.runtime.session_registry.get_session_actor(session_id) is None

    def reject_disk_scan(*_args: object) -> None:
        pytest.fail("Cold status must use the existing session index, not scan all history.")

    monkeypatch.setattr("klaude_code.server.session_index.resolve_session_work_dir", reject_disk_scan)
    after = _get_row(app_env, session_id)
    assert after["state"] == "needs_you"
    assert after["status"] == before["status"]
    assert after["status"]["continuation"]["triggers"] == ["queue"]
    assert after["status"]["control"]["paused"] is True
    assert app_env.fake_llm.call_count == 0


def test_resume_running_durable_input_is_idempotent(app_env: AppEnv) -> None:
    _enqueue_text_reply(app_env, "done once", delay_s=0.3)
    _enqueue_text_reply(app_env, "must not run")
    session_id = _run(app_env)["session_id"]
    deadline = time.monotonic() + 5
    while app_env.fake_llm.call_count == 0 and time.monotonic() < deadline:
        time.sleep(0.01)
    assert app_env.fake_llm.call_count == 1
    for _ in range(3):
        response = app_env.client.post(f"/api/headless/sessions/{session_id}/control", json={"action": "resume"})
        assert response.status_code == 200
    _wait_for_state(app_env, session_id, "idle")
    time.sleep(0.1)
    assert app_env.fake_llm.call_count == 1


def test_dismiss_without_an_error_does_not_pause_queued_work(app_env: AppEnv) -> None:
    _enqueue_text_reply(app_env, "first reply", delay_s=0.3)
    _enqueue_text_reply(app_env, "second reply")
    session_id = _run(app_env)["session_id"]
    deadline = time.monotonic() + 5
    while app_env.fake_llm.call_count == 0 and time.monotonic() < deadline:
        time.sleep(0.01)
    assert app_env.fake_llm.call_count == 1
    response = app_env.client.post(f"/api/headless/sessions/{session_id}/send", json={"text": "follow up"})
    assert response.status_code == 200
    response = app_env.client.post(f"/api/headless/sessions/{session_id}/control", json={"action": "dismiss"})
    assert response.status_code == 200
    assert response.json()["status"]["control"]["paused"] is False
    _wait_for_state(app_env, session_id, "idle")
    output = app_env.client.get(f"/api/headless/sessions/{session_id}/output").json()
    assert output["output"] == "second reply"
    assert Session.load_meta(session_id, app_env.work_dir).follow_up_queue == []


def test_attention_sorts_before_more_recent_work(app_env: AppEnv) -> None:
    failed_id = _run(app_env, "no fake response")["session_id"]
    _wait_for_state(app_env, failed_id, "needs_you")
    _enqueue_text_reply(app_env, "newer work", delay_s=0.3)
    working_id = _run(app_env, "newer request")["session_id"]
    rows = app_env.client.get("/api/headless/sessions").json()["sessions"]
    assert [row["id"] for row in rows] == [failed_id, working_id]
    assert [row["state"] for row in rows] == ["needs_you", "working"]


@pytest.mark.parametrize("explicit_model", [False, True])
def test_headless_role_model_source_survives_restore_and_explicit_configuration(
    app_env: AppEnv, monkeypatch: pytest.MonkeyPatch, explicit_model: bool
) -> None:
    config = Config(
        main_model="main",
        sub_agent_models={"code-reviewer": ["review-primary", "review-backup"]},
        provider_list=[
            ProviderConfig(
                provider_name="test",
                protocol=llm_param.LLMClientProtocol.OPENAI,
                api_key="test-key",
                model_list=[ModelConfig(model_name=name) for name in ("main", "review-primary", "review-backup")],
            )
        ],
    )
    monkeypatch.setattr("klaude_code.config.load_config", lambda: config)

    async def queued_spawn(**_kwargs: Any) -> str:
        return "queued"

    monkeypatch.setattr(_headless_runtime(app_env), "spawn", queued_spawn)
    extra = {"model": "review-primary"} if explicit_model else {}
    body = _run(app_env, agent="code-reviewer", **extra)
    session_id = body["session_id"]
    restored = Session.load(session_id, work_dir=app_env.work_dir)

    assert restored.sub_agent_state is None
    assert restored.model_config_name == "review-primary"
    assert restored.model_from_role is not explicit_model
    expected = ["review-primary@test"]
    if not explicit_model:
        expected += ["review-backup@test", "main@test"]
    assert [candidate.selector for candidate in _session_model_candidates(restored, config).candidates] == expected

    response = app_env.client.put(f"/api/sessions/{session_id}/model/config", json={"model_name": "review-primary"})
    assert response.status_code == 200
    configured = Session.load(session_id, work_dir=app_env.work_dir)
    assert configured.model_from_role is False
    assert [candidate.selector for candidate in _session_model_candidates(configured, config).candidates] == [
        "review-primary@test"
    ]


def test_connection_does_not_change_session_status(app_env: AppEnv) -> None:
    _enqueue_text_reply(app_env, "all done")
    body = _run(app_env, "say done")
    session_id = body["session_id"]
    _wait_for_state(app_env, session_id, "idle")

    with app_env.client.websocket_connect(f"/api/sessions/{session_id}/ws?replay=1") as websocket:
        info = websocket.receive_json()
        assert info["type"] == "connection_info"
        row = _wait_for_state(app_env, session_id, "idle")
        assert row["state"] == "idle"

    _wait_for_state(app_env, session_id, "idle")


def test_peek_attach_keeps_session_completed(app_env: AppEnv) -> None:
    _enqueue_text_reply(app_env, "all done")
    body = _run(app_env, "say done")
    session_id = body["session_id"]
    _wait_for_state(app_env, session_id, "idle")

    # A read-only viewer (output --follow) is not a human at a prompt.
    with app_env.client.websocket_connect(f"/api/sessions/{session_id}/ws?replay=1&peek=1") as websocket:
        info = websocket.receive_json()
        assert info["type"] == "connection_info"
        assert _get_row(app_env, session_id)["state"] == "idle"


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
    assert second["status"]["execution"] == "queued"
    assert third["status"]["execution"] == "queued"
    assert fourth["status"]["execution"] == "queued"
    assert {_get_row(app_env, item["session_id"])["state"] for item in (second, third, fourth)} == {"working"}

    _wait_for_state(app_env, first["session_id"], "idle")
    # _pump must reserve the one slot before creating a launch task. The old
    # implementation started all three queued runs in this transition.
    queued_states = [_get_row(app_env, item["session_id"])["status"]["execution"] for item in (second, third, fourth)]
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
    assert second["status"]["execution"] == "queued"

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
    assert response.json()["mode"] == "queued"

    _wait_for_state(app_env, session_id, "idle")
    output = app_env.client.get(f"/api/headless/sessions/{session_id}/output").json()
    assert output["output"] == "turn two"


def test_send_with_from_label_preserves_structured_peer(app_env: AppEnv) -> None:
    _enqueue_text_reply(app_env, "turn one")
    body = _run(app_env, "start")
    session_id = body["session_id"]
    _wait_for_state(app_env, session_id, "idle")

    _enqueue_text_reply(app_env, "turn two")
    response = app_env.client.post(
        f"/api/headless/sessions/{session_id}/send",
        json={"text": "hello from a peer", "sender": "reviewer"},
    )
    assert response.status_code == 200
    _wait_for_state(app_env, session_id, "idle")

    output = app_env.client.get(f"/api/headless/sessions/{session_id}/output", params={"transcript": True}).json()
    assert '"sender_label":"reviewer"' in output["output"]
    assert "source=peer_message" in output["output"]
    assert "hello from a peer" in output["output"]


def test_send_claimed_session_id_does_not_establish_identity(app_env: AppEnv) -> None:
    _enqueue_text_reply(app_env, "sender done")
    sender = _run(app_env, "I am the sender", name="peer-agent")
    _wait_for_state(app_env, sender["session_id"], "idle")

    _enqueue_text_reply(app_env, "target turn one")
    target = _run(app_env, "I am the target")
    target_id = target["session_id"]
    _wait_for_state(app_env, target_id, "idle")

    _enqueue_text_reply(app_env, "target turn two")
    response = app_env.client.post(
        f"/api/headless/sessions/{target_id}/send",
        json={"text": "message across agents", "sender_session_id": sender["session_id"]},
    )
    assert response.status_code == 200
    _wait_for_state(app_env, target_id, "idle")

    output = app_env.client.get(f"/api/headless/sessions/{target_id}/output", params={"transcript": True}).json()
    assert '"sender_label":"external"' in output["output"]
    assert sender["session_id"] not in output["output"]


def test_send_without_sender_is_still_peer_data(app_env: AppEnv) -> None:
    _enqueue_text_reply(app_env, "turn one")
    body = _run(app_env, "start")
    session_id = body["session_id"]
    _wait_for_state(app_env, session_id, "idle")

    _enqueue_text_reply(app_env, "turn two")
    response = app_env.client.post(f"/api/headless/sessions/{session_id}/send", json={"text": "plain operator text"})
    assert response.status_code == 200
    _wait_for_state(app_env, session_id, "idle")

    output = app_env.client.get(f"/api/headless/sessions/{session_id}/output", params={"transcript": True}).json()
    assert "plain operator text" in output["output"]
    assert "source=peer_message" in output["output"]


def test_send_idle_headless_session_obeys_global_slot(app_env: AppEnv) -> None:
    _enqueue_text_reply(app_env, "existing done")
    existing = _run(app_env, "existing")
    _wait_for_state(app_env, existing["session_id"], "idle")

    headless = _headless_runtime(app_env)
    headless._max_running = 1  # type: ignore[attr-defined] # pyright: ignore[reportPrivateUsage]
    _enqueue_text_reply(app_env, "blocker done", delay_s=0.5)
    _enqueue_text_reply(app_env, "sent done")
    blocker = _run(app_env, "block the slot")
    _wait_for_state(app_env, blocker["session_id"], "working")

    response = app_env.client.post(
        f"/api/headless/sessions/{existing['session_id']}/send",
        json={"text": "must wait for a slot"},
    )
    assert response.status_code == 200
    assert response.json()["mode"] == "queued"
    row = _get_row(app_env, existing["session_id"])
    assert row["status"]["execution"] == "queued"
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
    _wait_for_state(app_env, blocker["session_id"], "working")

    created = app_env.client.post("/api/sessions", json={"work_dir": str(app_env.work_dir)})
    assert created.status_code == 200
    interactive_id = created.json()["session_id"]
    _enqueue_text_reply(app_env, "interactive done")

    response = app_env.client.post(
        f"/api/headless/sessions/{interactive_id}/send",
        json={"text": "run independently"},
    )

    assert response.status_code == 200
    assert response.json()["mode"] == "queued"
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
    _wait_for_state(app_env, session_id, "working")
    deadline = time.time() + 8.0
    while app_env.fake_llm.call_count < 1 and time.time() < deadline:
        time.sleep(0.01)
    assert app_env.fake_llm.call_count == 1

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
        assert row["state"] == "working" or row["pending"] is True
        time.sleep(0.05)
    assert output["output"] == "follow-up reply"


@pytest.mark.parametrize("headless_session", [True, False])
def test_input_arriving_during_task_teardown_is_not_stranded(
    app_env: AppEnv, monkeypatch: pytest.MonkeyPatch, headless_session: bool
) -> None:
    handler = app_env.runtime._operation_dispatcher._agent_operation_handler
    original_emit = handler._emit_event
    queued_late = False

    async def emit(event: events.Event) -> None:
        nonlocal queued_late
        if isinstance(event, events.TaskMetadataEvent) and not queued_late:
            queued_late = True
            await app_env.runtime.submit_and_wait(
                op.FollowUpAgentOperation(
                    session_id=event.session_id, input=message.UserInputPayload(text="late input")
                )
            )
        await original_emit(event)

    monkeypatch.setattr(handler, "_emit_event", emit)
    _enqueue_text_reply(app_env, "first done")
    _enqueue_text_reply(app_env, "late done")
    if headless_session:
        session_id = _run(app_env, "initial")["session_id"]
    else:
        session_id = app_env.create_session()
        response = app_env.client.post(f"/api/headless/sessions/{session_id}/send", json={"text": "initial"})
        assert response.status_code == 200
    _wait_for_state(app_env, session_id, "idle")
    assert queued_late
    output = app_env.client.get(f"/api/headless/sessions/{session_id}/output").json()
    assert output["output"] == "late done" and output["pending"] is False
    session = Session.load(session_id, work_dir=app_env.work_dir)
    assert [
        item.peer_message.body if item.peer_message is not None else message.join_text_parts(item.parts)
        for item in session.conversation_history
        if isinstance(item, message.UserMessage)
    ] == ["initial", "late input"]
    assert session.follow_up_queue == []


def test_brief_shows_bounded_latest_turn_activity(app_env: AppEnv, monkeypatch: pytest.MonkeyPatch) -> None:
    _enqueue_text_reply(app_env, "done")
    session_id = _run(app_env)["session_id"]
    _wait_for_state(app_env, session_id, "idle")
    session = Session.load(session_id, work_dir=app_env.work_dir)
    session.conversation_history = [
        message.UserMessage(parts=[message.TextPart(text="old task")]),
        message.AssistantMessage(
            parts=[message.ToolCallPart(call_id="old", tool_name="Bash", arguments_json='{"command":"old"}')]
        ),
        message.UserMessage(parts=[message.TextPart(text="latest request " * 40)]),
        message.UserMessage(source="bash_mode", parts=[message.TextPart(text="manual command")]),
    ]
    statuses = ["success", "success", "error", "aborted", "success", "success", "pending"]
    for index, status in enumerate(statuses):
        if index == 6:
            session.conversation_history.extend(
                [
                    message.UserMessage(parts=[message.TextPart(text=EMPTY_RESPONSE_CONTINUATION_PROMPT)]),
                    message.UserMessage(
                        parts=[message.TextPart(text=build_stream_error_continuation_prompt("partial output"))]
                    ),
                    message.UserMessage(
                        parts=[
                            message.TextPart(text=f"<system-reminder>{FORK_CONTEXT_GENERAL_PROMPT}</system-reminder>")
                        ]
                    ),
                ]
            )
        session.conversation_history.append(
            message.AssistantMessage(
                parts=[
                    message.TextPart(text=f"progress-{index}: " + "x" * 1000 + f" tail-{index}"),
                    message.ThinkingTextPart(text="internal reasoning should not appear"),
                    message.ToolCallPart(
                        call_id=f"call-{index}",
                        tool_name="Bash",
                        arguments_json=json.dumps({"command": f"step-{index} " + "x" * 200}),
                    ),
                ]
            )
        )
        if status != "pending":
            session.conversation_history.append(
                message.ToolResultMessage(
                    call_id=f"call-{index}", status=cast(ToolStatus, status), output_text="must not appear in brief"
                )
            )
    monkeypatch.setattr("klaude_code.server.routes.headless._load_session_for_read", lambda *_args: session)

    response = app_env.client.get(f"/api/headless/sessions/{session_id}/brief")

    assert response.status_code == 200
    brief = response.json()
    assert brief["last_user_message"].startswith("latest request")
    assert len(brief["last_user_message"]) == 300
    tools = brief["recent_tool_calls"]
    assert [tool["call_id"] for tool in tools] == [f"call-{index}" for index in range(2, 7)]
    assert [tool["status"] for tool in tools] == statuses[2:]
    assert all(len(tool["activity"]) <= 120 for tool in tools)
    assert "must not appear" not in response.text
    assert "internal reasoning" not in response.text
    texts = brief["recent_assistant_messages"]
    assert len(texts) == 5
    assert all(len(text) <= 300 for text in texts[:-1])
    assert texts[0].startswith("progress-2:") and texts[0].endswith("tail-2")
    assert "middle truncated" in texts[0]
    assert texts[-1] == "progress-6: " + "x" * 1000 + " tail-6"
    assert brief["last_assistant_message"] == texts[-1]
    assert brief["assistant_streaming"] is False

    session.conversation_history.append(message.UserMessage(parts=[message.TextPart(text="new task")]))
    brief = app_env.client.get(f"/api/headless/sessions/{session_id}/brief").json()
    assert brief["last_user_message"] == "new task"
    assert brief["recent_tool_calls"] == []
    assert brief["recent_assistant_messages"] == []
    assert brief["last_assistant_message"] == ""


def test_brief_includes_streaming_text_without_repeating_finished_message(app_env: AppEnv) -> None:
    _enqueue_text_reply(app_env, "previous turn")
    session_id = _run(app_env)["session_id"]
    _wait_for_state(app_env, session_id, "idle")
    app_env.fake_llm.enqueue(
        message.AssistantTextDelta(content="checking ", response_id="brief-stream"),
        message.ThinkingTextDelta(content="private reasoning", response_id="brief-stream"),
        message.AssistantTextDelta(content="the tests", response_id="brief-stream"),
        message.AssistantMessage(
            parts=[message.TextPart(text="checking the tests")],
            response_id="brief-stream",
            stop_reason="stop",
        ),
        delay_s=0.3,
    )
    response = app_env.client.post(f"/api/headless/sessions/{session_id}/send", json={"text": "new task"})
    assert response.status_code == 200

    deadline = time.time() + 8.0
    brief: dict[str, Any] = {}
    while time.time() < deadline:
        brief = app_env.client.get(f"/api/headless/sessions/{session_id}/brief").json()
        if brief["assistant_streaming"] and brief["last_assistant_message"] == "checking the tests":
            break
        time.sleep(0.02)
    assert brief["assistant_streaming"] is True
    assert brief["last_assistant_message"] == "checking the tests"
    assert brief["recent_assistant_messages"] == ["checking the tests"]

    _wait_for_state(app_env, session_id, "idle")
    brief = app_env.client.get(f"/api/headless/sessions/{session_id}/brief").json()
    assert brief["assistant_streaming"] is False
    assert brief["last_assistant_message"] == "checking the tests"
    assert brief["recent_assistant_messages"] == ["checking the tests"]


def test_waiting_input_brief_and_respond(app_env: AppEnv) -> None:
    _enqueue_ask_question(app_env)
    body = _run(app_env, "ask me")
    session_id = body["session_id"]
    _wait_for_state(app_env, session_id, "needs_you")
    assert _get_row(app_env, session_id)["pending"] is False

    brief = app_env.client.get(f"/api/headless/sessions/{session_id}/brief").json()
    assert brief["state"] == "needs_you"
    assert brief["last_user_message"] == "ask me"
    assert brief["recent_tool_calls"][0]["call_id"] == "call-1"
    assert brief["recent_tool_calls"][0]["status"] == "pending"
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
    assert response.json()["response_status"] == "submitted"

    _wait_for_state(app_env, session_id, "idle")
    brief = app_env.client.get(f"/api/headless/sessions/{session_id}/brief").json()
    assert brief["current_tool_call"] is None
    assert brief["recent_tool_calls"][0]["status"] == "success"
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
    _wait_for_state(app_env, session_id, "working")

    response = app_env.client.post(f"/api/headless/sessions/{session_id}/interrupt")
    assert response.status_code == 200
    row = _wait_for_state(app_env, session_id, "idle")
    assert row["status"]["last_turn"]["result"] == "interrupted"
    assert row["status"]["attention"] == []


def test_kill_running_session_cancels_queued_follow_up(app_env: AppEnv) -> None:
    _enqueue_text_reply(app_env, "slow reply", delay_s=0.6)
    body = _run(app_env, "long task")
    session_id = body["session_id"]
    _wait_for_state(app_env, session_id, "working")

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


def test_steer_continues_current_task_without_interrupting_stream(app_env: AppEnv) -> None:
    _enqueue_text_reply(app_env, "original stream completed", delay_s=1.0)
    body = _run(app_env, "long task")
    session_id = body["session_id"]
    _wait_for_state(app_env, session_id, "working")
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
    assert row["state"] == "working" or row["pending"] is True

    deadline = time.time() + 8.0
    output: dict[str, Any] = {}
    while time.time() < deadline:
        row = _get_row(app_env, session_id)
        output = app_env.client.get(f"/api/headless/sessions/{session_id}/output").json()
        if row["state"] == "idle" and not output["pending"]:
            break
        assert row["state"] == "working" or row["pending"] is True
        time.sleep(0.05)
    assert row["state"] == "idle"
    assert output["pending"] is False
    assert output["output"] == "steered result"
    session = Session.load(session_id, work_dir=app_env.work_dir)
    assert not any(isinstance(item, message.InterruptEntry) for item in session.conversation_history)
    assert any(
        isinstance(item, message.AssistantMessage)
        and message.join_text_parts(item.parts) == "original stream completed"
        for item in session.conversation_history
    )


def test_failed_persists_and_clears_when_next_turn_starts(app_env: AppEnv) -> None:
    body = _run(app_env, "this call has no fake response")
    session_id = body["session_id"]
    _wait_for_state(app_env, session_id, "needs_you")

    meta_path = next((app_env.home_dir / ".klaude" / "projects").glob(f"*/sessions/{session_id}/meta.json"))
    assert json.loads(meta_path.read_text())["runtime"]["error"] is not None

    _enqueue_text_reply(app_env, "recovered")
    response = app_env.client.post(f"/api/headless/sessions/{session_id}/send", json={"text": "retry"})
    assert response.status_code == 200
    assert _get_row(app_env, session_id)["state"] == "needs_you"
    dismissed = app_env.client.post(f"/api/headless/sessions/{session_id}/control", json={"action": "dismiss"})
    assert dismissed.status_code == 200
    assert dismissed.json()["status"]["last_turn"]["result"] == "failed"
    assert {reason["kind"] for reason in dismissed.json()["status"]["attention"]} == {"paused"}
    assert app_env.fake_llm.call_count == 1
    resumed = app_env.client.post(f"/api/headless/sessions/{session_id}/control", json={"action": "resume"})
    assert resumed.status_code == 200
    _wait_for_state(app_env, session_id, "idle")
    assert json.loads(meta_path.read_text())["runtime"]["error"] is None


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


@pytest.mark.parametrize("count", [0, 1, 3, 4, 6, 7, 10])
def test_output_preview_bounds_and_filters_user_messages(
    app_env: AppEnv, monkeypatch: pytest.MonkeyPatch, count: int
) -> None:
    session_id = app_env.create_session()
    session = Session.load(session_id, work_dir=app_env.work_dir)
    inputs = [f"input-{index} <file> & " + "界" * 3000 for index in range(count)]
    for index, value in enumerate(inputs):
        if index % 3 == 2:
            escaped = value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            value = (
                "<local-command-caveat>System instructions</local-command-caveat>"
                f"<bash-input>{escaped}</bash-input><bash-stdout>command output</bash-stdout>"
            )
        session.conversation_history.append(
            message.UserMessage(
                source=(None, "user", "bash_mode")[index % 3],
                parts=[message.TextPart(text=value[:8]), message.TextPart(text=value[8:])],
            )
        )
    for source in ("shell_completion", "task_completion", "peer_message"):
        session.conversation_history.append(
            message.UserMessage(
                source=cast(message.UserMessageSource, source), parts=[message.TextPart(text="callback")]
            )
        )
    session.conversation_history.append(message.AssistantMessage(parts=[message.TextPart(text="r" * 20000)]))
    monkeypatch.setattr(headless_routes, "_load_session_for_read", lambda *_args: session)
    path = f"/api/headless/sessions/{session_id}/output"
    default = app_env.client.get(path).json()
    assert default["output"] == "r" * 20000
    assert "user_messages" not in default and "user_message_count" not in default
    response = app_env.client.get(path, params={"preview": True})
    assert response.status_code == 200
    preview = response.json()
    expected = inputs if count <= 6 else inputs[:3] + inputs[-3:]
    assert preview["user_message_count"] == count
    assert len(preview["user_messages"]) == min(count, 6)
    assert all(len(value) <= 2000 for value in preview["user_messages"])
    assert preview["user_messages"] == [value[:2000] for value in expected]
    assert preview["output"] == "r" * 12000


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
