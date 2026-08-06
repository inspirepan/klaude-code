# pyright: reportPrivateUsage=false

"""A session's clients must come from the current config, not the startup one."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from klaude_code.agent.runtime import agent_ops as agent_ops_module
from klaude_code.agent.runtime.agent_ops import AgentOperationHandler
from klaude_code.agent.runtime.llm import LLMClients
from klaude_code.config.config import Config, ModelConfig, ProviderConfig
from klaude_code.llm.client import LLMClientABC
from klaude_code.protocol import llm_param, user_interaction
from klaude_code.session.session import Session


class _StubClient(LLMClientABC):
    def __init__(self, model_id: str) -> None:
        super().__init__(
            llm_param.LLMConfigParameter(
                provider_name="test",
                protocol=llm_param.LLMClientProtocol.OPENAI,
                model_id=model_id,
            )
        )

    @classmethod
    def create(cls, config: llm_param.LLMConfigParameter) -> LLMClientABC:
        return cls(config.model_id or "")

    async def call(self, param: llm_param.LLMCallParameter) -> Any:
        raise AssertionError("this test never calls the model")


class _StubActor:
    def __init__(self) -> None:
        self.clients: LLMClients | None = None

    def get_llm_clients(self) -> LLMClients | None:
        return self.clients

    def set_llm_clients(self, clients: LLMClients) -> None:
        self.clients = clients


def _handler(template_alias: str) -> tuple[AgentOperationHandler, _StubActor]:
    actor = _StubActor()

    async def _emit(_event: Any) -> None:
        return None

    async def _request_user_interaction(_request: Any) -> user_interaction.UserInteractionResponse:
        raise AssertionError("no interaction expected")

    handler = AgentOperationHandler(
        emit_event=_emit,
        llm_clients=LLMClients(main=_StubClient("startup-model-id"), main_model_alias=template_alias),
        model_profile_provider=Any,  # ty: ignore[invalid-argument-type] # unused by _ensure_session_llm_clients
        on_child_task_state_change=lambda *_args: None,
        ensure_session_actor=lambda _sid: actor,  # ty: ignore[invalid-argument-type] # pyright: ignore[reportArgumentType]
        get_session_actor=lambda _sid: None,
        get_session_actor_for_operation=lambda _op: None,
        list_session_actors=lambda: [],
        register_task=lambda *_args: None,
        remove_task=lambda *_args: None,
        request_user_interaction=_request_user_interaction,
    )
    return handler, actor


def _config_with_main_model(model_name: str) -> Config:
    return Config(
        main_model=model_name,
        provider_list=[
            ProviderConfig(
                provider_name="test-provider",
                protocol=llm_param.LLMClientProtocol.OPENAI,
                api_key="test-key",
                model_list=[ModelConfig(model_name=model_name, model_id=f"{model_name}-id")],
            )
        ],
    )


def test_new_session_uses_the_current_main_model(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """/model saves a new default; sessions created later must pick it up."""
    handler, actor = _handler("startup-model")
    monkeypatch.setattr(agent_ops_module, "load_config", lambda: _config_with_main_model("switched-model"))

    session = Session(work_dir=tmp_path)
    clients = handler._ensure_session_llm_clients(session)

    assert clients.main_model_alias == "switched-model"
    assert clients.main.get_llm_config().model_id == "switched-model-id"
    assert actor.clients is clients


def test_new_session_falls_back_to_startup_clients_when_config_cannot_resolve(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unresolvable config must not break session creation."""
    handler, _actor = _handler("startup-model")
    monkeypatch.setattr(agent_ops_module, "load_config", lambda: Config(main_model=None, provider_list=[]))

    session = Session(work_dir=tmp_path)
    clients = handler._ensure_session_llm_clients(session)

    assert clients.main_model_alias == "startup-model"
    assert clients.main.get_llm_config().model_id == "startup-model-id"


def test_session_model_override_still_wins(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A session pinned to a model keeps it even when the default changed."""
    handler, _actor = _handler("startup-model")
    config = _config_with_main_model("switched-model")
    config.provider_list[0].model_list.append(ModelConfig(model_name="pinned-model", model_id="pinned-model-id"))
    monkeypatch.setattr(agent_ops_module, "load_config", lambda: config)

    session = Session(work_dir=tmp_path)
    session.model_config_name = "pinned-model"
    clients = handler._ensure_session_llm_clients(session)

    assert clients.main.get_llm_config().model_id == "pinned-model-id"
