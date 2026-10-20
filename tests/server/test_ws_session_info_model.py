"""The session_info frame must name the model the next request will run.

``model_config_name`` stays the stored selector (it is what rehydrates the
session); the prompt bar reads ``active_model_name``, which comes from the live
client so a session-model fallback or a runtime fallback is visible.
"""

from __future__ import annotations

from dataclasses import replace
from functools import partial
from typing import Any, cast

from klaude_code.agent.runtime.llm import FallbackLLMClient
from klaude_code.config.config import ModelConfigCandidate
from klaude_code.protocol import events, llm_param
from klaude_code.server.routes.ws import _build_session_info

from .conftest import AppEnv, receive_events


def _state(app_env: AppEnv) -> Any:
    return cast(Any, app_env.client.app).state.server_state


def _agent(app_env: AppEnv, session_id: str) -> Any:
    actor = app_env.runtime.session_registry.get_session_actor(session_id)
    assert actor is not None
    agent = actor.get_agent()
    assert agent is not None
    return agent


def _candidate(selector: str) -> ModelConfigCandidate:
    model_name, _, provider = selector.partition("@")
    return ModelConfigCandidate(
        selector=selector,
        model_name=model_name,
        provider=provider,
        llm_config=llm_param.LLMConfigParameter(
            provider_name=provider,
            protocol=llm_param.LLMClientProtocol.OPENAI,
            model_id=f"{model_name}-upstream-id",
        ),
    )


def _use_client(app_env: AppEnv, session_id: str, client: FallbackLLMClient) -> None:
    """Swap the agent's client the way a model change does."""
    agent = _agent(app_env, session_id)
    agent.set_model_profile(replace(agent.profile, llm_client=client))


def _next_session_info(websocket: Any, max_frames: int = 40) -> dict[str, Any]:
    for _ in range(max_frames):
        for item in receive_events(websocket):
            if item.get("type") == "session_info":
                return item
    raise AssertionError("no session_info frame arrived")


def _drain_attach(websocket: Any) -> None:
    """Read the handshake through replay_complete."""
    while True:
        for item in receive_events(websocket):
            if item.get("type") == "replay_complete":
                return


def test_session_info_names_the_model_the_client_will_run(app_env: AppEnv) -> None:
    """The stored selector is what was asked for; the client decides what runs."""
    session_id = app_env.create_session()
    agent = _agent(app_env, session_id)
    agent.session.model_config_name = "removed-model"

    with app_env.client.websocket_connect(f"/api/sessions/{session_id}/ws?replay=1") as websocket:
        info = _next_session_info(websocket)

    assert info["model_config_name"] == "removed-model"
    # The session ran the default client; the bar must say so, not echo the selector.
    assert info["active_model_name"] == "fake-model"


def test_session_info_follows_a_runtime_fallback(app_env: AppEnv) -> None:
    """A fallback advances the active candidate in place, without a new client."""
    session_id = app_env.create_session()
    agent = _agent(app_env, session_id)
    client = FallbackLLMClient([_candidate("sonnet@anthropic"), _candidate("opus@anthropic")])
    _use_client(app_env, session_id, client)
    agent.session.model_config_name = "sonnet@anthropic"

    assert _build_session_info(_state(app_env), session_id)["active_model_name"] == "sonnet"

    assert client.fallback_to_next() is not None

    info = _build_session_info(_state(app_env), session_id)
    assert info["model_config_name"] == "sonnet@anthropic"
    assert info["active_model_name"] == "opus"
    assert info["provider_name"] == "anthropic"


def test_fallback_event_refreshes_the_session_info(app_env: AppEnv) -> None:
    """The client learns the new active model from the event, not by re-asking."""
    session_id = app_env.create_session()
    client = FallbackLLMClient([_candidate("sonnet@anthropic"), _candidate("opus@anthropic")])
    _use_client(app_env, session_id, client)

    with app_env.client.websocket_connect(f"/api/sessions/{session_id}/ws?replay=1") as websocket:
        _drain_attach(websocket)
        assert client.fallback_to_next() is not None
        websocket.portal.call(
            partial(
                app_env.event_bus.publish,
                events.FallbackModelConfigWarnEvent(
                    session_id=session_id,
                    from_model="sonnet",
                    to_model="opus",
                    reason="quota exceeded",
                ),
            )
        )
        info = _next_session_info(websocket)

    assert info["active_model_name"] == "opus"
