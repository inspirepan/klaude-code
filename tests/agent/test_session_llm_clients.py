# pyright: reportPrivateUsage=false

"""A session's clients must come from the current config, not the startup one."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

import pytest

from klaude_code.agent.agent import Agent
from klaude_code.agent.agent_profile import AgentProfile
from klaude_code.agent.runtime import agent_ops as agent_ops_module
from klaude_code.agent.runtime import llm as llm_module
from klaude_code.agent.runtime.agent_ops import AgentOperationHandler
from klaude_code.agent.runtime.config_ops import ModelSwitcher
from klaude_code.agent.runtime.llm import FallbackLLMClient, LLMClients
from klaude_code.config.config import Config, ModelConfig, ProviderConfig
from klaude_code.llm.client import LLMClientABC
from klaude_code.protocol import events, llm_param, message, user_interaction
from klaude_code.protocol.models import SubAgentState
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


@pytest.fixture(autouse=True)
def _stub_client_factory(monkeypatch: pytest.MonkeyPatch) -> None:
    """Cloning a stub must not create a real provider SDK client."""
    monkeypatch.setattr(llm_module, "create_llm_client", _StubClient.create)


class _StubActor:
    def __init__(self) -> None:
        self.clients: LLMClients | None = None
        self.agent: Any = None
        self.pending_model_fallback_warn: events.FallbackModelConfigWarnEvent | None = None

    def get_llm_clients(self) -> LLMClients | None:
        return self.clients

    def set_llm_clients(self, clients: LLMClients) -> None:
        self.clients = clients

    def get_agent(self) -> Any:
        return self.agent

    def set_agent(self, agent: Any) -> None:
        self.agent = agent

    def set_pending_model_fallback_warn(self, event: events.FallbackModelConfigWarnEvent) -> None:
        self.pending_model_fallback_warn = event

    def consume_pending_model_fallback_warn(self) -> events.FallbackModelConfigWarnEvent | None:
        event = self.pending_model_fallback_warn
        self.pending_model_fallback_warn = None
        return event


class _StubProfileProvider:
    """Builds a profile straight from the client; no prompts, tools, or disk scan."""

    def build_profile(
        self,
        llm_client: LLMClientABC,
        sub_agent_type: str | None = None,
        *,
        work_dir: Path,
    ) -> AgentProfile:
        del sub_agent_type, work_dir
        return AgentProfile(llm_client=llm_client, system_prompt=None, tools=[], attachments=[])


def _handler(
    template_alias: str,
    *,
    parent_actors: dict[str, _StubActor] | None = None,
    emitted: list[Any] | None = None,
    profile_provider: Any = Any,
) -> tuple[AgentOperationHandler, _StubActor]:
    actor = _StubActor()
    parents = parent_actors or {}
    events_out = emitted if emitted is not None else []

    async def _emit(event: Any) -> None:
        events_out.append(event)

    async def _request_user_interaction(_request: Any) -> user_interaction.UserInteractionResponse:
        raise AssertionError("no interaction expected")

    handler = AgentOperationHandler(
        emit_event=_emit,
        llm_clients=LLMClients(main=_StubClient("startup-model-id"), main_model_alias=template_alias),
        # The provider is only reached by the agent-initializing entry points.
        model_profile_provider=profile_provider,
        on_child_task_state_change=lambda *_args: None,
        ensure_session_actor=lambda _sid: actor,  # ty: ignore[invalid-argument-type] # pyright: ignore[reportArgumentType]
        get_session_actor=lambda sid: parents.get(sid),  # ty: ignore[invalid-argument-type] # pyright: ignore[reportArgumentType]
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
    clients = handler._ensure_session_llm_clients(session).clients

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
    clients = handler._ensure_session_llm_clients(session).clients

    assert clients.main_model_alias == "startup-model"
    assert isinstance(clients.main, _StubClient)
    assert clients.main is not handler._llm_clients_template.main
    assert clients.main.get_llm_config().model_id == "startup-model-id"


def test_session_model_override_still_wins(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A session pinned to a model keeps it even when the default changed."""
    handler, _actor = _handler("startup-model")
    config = _config_with_main_model("switched-model")
    config.provider_list[0].model_list.append(ModelConfig(model_name="pinned-model", model_id="pinned-model-id"))
    monkeypatch.setattr(agent_ops_module, "load_config", lambda: config)

    session = Session(work_dir=tmp_path)
    session.model_config_name = "pinned-model"
    clients = handler._ensure_session_llm_clients(session).clients

    assert clients.main.get_llm_config().model_id == "pinned-model-id"


def _config_with_two_providers() -> Config:
    return Config(
        main_model=None,
        provider_list=[
            ProviderConfig(
                provider_name=name,
                protocol=llm_param.LLMClientProtocol.OPENAI,
                api_key="test-key",
                model_list=[ModelConfig(model_name="kimi", model_id=f"kimi-{name}")],
            )
            for name in ("first-provider", "parent-provider")
        ],
    )


def _parent_actor(provider_name: str) -> _StubActor:
    parent = _StubActor()
    parent_client = _StubClient("parent-model-id")
    parent_client.get_llm_config().provider_name = provider_name
    parent.clients = LLMClients(main=parent_client)
    return parent


@pytest.mark.parametrize(
    ("model_config_name", "expected_providers"),
    [
        # Unqualified: the parent's provider goes first, the rest stays as fallback.
        ("kimi", ["parent-provider", "first-provider"]),
        # Provider-qualified: an explicit provider is never replaced.
        ("kimi@first-provider", ["first-provider"]),
    ],
)
def test_sub_agent_prefers_parent_provider_for_unqualified_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    model_config_name: str,
    expected_providers: list[str],
) -> None:
    handler, _actor = _handler("startup-model", parent_actors={"parent-id": _parent_actor("parent-provider")})
    monkeypatch.setattr(agent_ops_module, "load_config", _config_with_two_providers)

    session = Session(work_dir=tmp_path)
    session.parent_session_id = "parent-id"
    session.model_config_name = model_config_name
    clients = handler._ensure_session_llm_clients(session).clients

    assert isinstance(clients.main, FallbackLLMClient)
    assert [candidate.provider for candidate in clients.main.candidates] == expected_providers


def _config_with_role_chain(chain: list[str] | None = None) -> Config:
    def _provider(name: str, models: list[str]) -> ProviderConfig:
        return ProviderConfig(
            provider_name=name,
            protocol=llm_param.LLMClientProtocol.OPENAI,
            api_key="test-key",
            model_list=[ModelConfig(model_name=model, model_id=f"{model}-id") for model in models],
        )

    return Config(
        main_model="sonnet",
        sub_agent_models={"code-reviewer": chain or ["gpt-6.1-sol:max", "opus"]},
        provider_list=[
            _provider("openrouter", ["gpt-6.1-sol:max"]),
            _provider("anthropic", ["opus", "sonnet"]),
        ],
    )


def _sub_agent_session(tmp_path: Path, *, model: str | None = None, fork_context: bool = False) -> Session:
    session = Session(work_dir=tmp_path)
    session.model_from_role = not fork_context and not (model or "").strip()
    session.sub_agent_state = SubAgentState(
        sub_agent_type="code-reviewer",
        sub_agent_desc="review",
        sub_agent_prompt="review the diff",
        model=model,
        fork_context=fork_context,
    )
    return session


def test_sub_agent_runs_its_whole_role_chain_with_the_main_model_as_tail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A provider can accept the request and still fail it, so the chain must survive.

    sub_agent.py::_resolve_child_model stores only the chain's first match, which
    leaves the child with nothing to fall back to when that provider answers 404.
    """
    handler, _actor = _handler("startup-model")
    monkeypatch.setattr(agent_ops_module, "load_config", _config_with_role_chain)

    session = _sub_agent_session(tmp_path)
    session.model_config_name = "gpt-6.1-sol:max"
    clients = handler._ensure_session_llm_clients(session).clients

    assert isinstance(clients.main, FallbackLLMClient)
    assert [candidate.selector for candidate in clients.main.candidates] == [
        "gpt-6.1-sol:max@openrouter",
        "opus@anthropic",
        "sonnet@anthropic",
    ]


def test_explicit_sub_agent_model_override_is_not_widened(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The Agent tool's `model` argument is a direct request, not a preference."""
    handler, _actor = _handler("startup-model")
    monkeypatch.setattr(agent_ops_module, "load_config", _config_with_role_chain)

    session = _sub_agent_session(tmp_path, model="opus")
    session.model_config_name = "opus"
    clients = handler._ensure_session_llm_clients(session).clients

    assert isinstance(clients.main, FallbackLLMClient)
    assert [candidate.selector for candidate in clients.main.candidates] == ["opus@anthropic"]


def test_fork_context_child_keeps_the_parent_model(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    handler, _actor = _handler("startup-model")
    monkeypatch.setattr(agent_ops_module, "load_config", _config_with_role_chain)

    session = _sub_agent_session(tmp_path, fork_context=True)
    session.model_config_name = "sonnet"
    clients = handler._ensure_session_llm_clients(session).clients

    assert isinstance(clients.main, FallbackLLMClient)
    assert [candidate.selector for candidate in clients.main.candidates] == ["sonnet@anthropic"]


def test_restored_fork_context_child_keeps_the_parent_model(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """sub_agent_state is not persisted, so the role alone must not override the parent.

    A fork child's stored model is the parent's, which can coincide with the first
    match of a chain configured for the fork role.
    """
    handler, _actor = _handler("startup-model")
    config = _config_with_role_chain(["sonnet", "opus"])
    config.sub_agent_models = {"general-purpose-fork-context": ["sonnet", "opus"]}
    monkeypatch.setattr(agent_ops_module, "load_config", lambda: config)

    session = Session(work_dir=tmp_path)
    session.agent_type = "general-purpose-fork-context"
    session.parent_session_id = "parent-id"
    session.spawn_kind = "subagent"
    session.model_config_name = "sonnet"
    clients = handler._ensure_session_llm_clients(session).clients

    assert isinstance(clients.main, FallbackLLMClient)
    assert [candidate.selector for candidate in clients.main.candidates] == ["sonnet@anthropic"]


def test_removed_provider_in_the_role_chain_falls_back_to_the_stored_selector(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    handler, _actor = _handler("startup-model")
    monkeypatch.setattr(
        agent_ops_module,
        "load_config",
        lambda: _config_with_role_chain(["sonnet@copilot", "opus"]),
    )

    session = _sub_agent_session(tmp_path)
    session.model_config_name = "sonnet"
    clients = handler._ensure_session_llm_clients(session).clients

    assert isinstance(clients.main, FallbackLLMClient)
    assert [candidate.selector for candidate in clients.main.candidates] == ["sonnet@anthropic"]


def test_headless_agent_session_runs_the_role_chain(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`klaude run --agent TYPE` carries its role in agent_type, not sub_agent_state."""
    handler, _actor = _handler("startup-model")
    monkeypatch.setattr(agent_ops_module, "load_config", _config_with_role_chain)

    session = Session(work_dir=tmp_path)
    session.agent_type = "code-reviewer"
    session.spawn_kind = "headless"
    # What headless._resolve_run_model stores: the chain's first available match.
    session.model_config_name = "gpt-6.1-sol:max"
    session.model_from_role = True
    clients = handler._ensure_session_llm_clients(session).clients

    assert isinstance(clients.main, FallbackLLMClient)
    assert [candidate.selector for candidate in clients.main.candidates] == [
        "gpt-6.1-sol:max@openrouter",
        "opus@anthropic",
        "sonnet@anthropic",
    ]


def test_headless_explicit_model_is_not_widened(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    handler, _actor = _handler("startup-model")
    monkeypatch.setattr(agent_ops_module, "load_config", _config_with_role_chain)

    session = Session(work_dir=tmp_path)
    session.agent_type = "code-reviewer"
    session.spawn_kind = "headless"
    session.model_config_name = "opus"
    clients = handler._ensure_session_llm_clients(session).clients

    assert isinstance(clients.main, FallbackLLMClient)
    assert [candidate.selector for candidate in clients.main.candidates] == ["opus@anthropic"]


def test_unresolvable_role_chain_falls_back_to_the_stored_selector(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    handler, _actor = _handler("startup-model")
    monkeypatch.setattr(
        agent_ops_module,
        "load_config",
        lambda: _config_with_role_chain(["gone-a", "gone-b"]),
    )

    session = _sub_agent_session(tmp_path)
    session.model_config_name = "sonnet"
    clients = handler._ensure_session_llm_clients(session).clients

    assert isinstance(clients.main, FallbackLLMClient)
    assert [candidate.selector for candidate in clients.main.candidates] == ["sonnet@anthropic"]


def _config_with_extra_model(model_name: str) -> Config:
    config = _config_with_main_model("switched-model")
    config.provider_list[0].model_list.append(ModelConfig(model_name=model_name, model_id=f"{model_name}-id"))
    return config


def test_legacy_role_metadata_does_not_widen_an_identical_selector(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    handler, _actor = _handler("startup-model")
    monkeypatch.setattr(agent_ops_module, "load_config", _config_with_role_chain)
    session = Session(work_dir=tmp_path, agent_type="code-reviewer", model_config_name="gpt-6.1-sol:max")
    session.ensure_meta_exists()
    session._store.update_meta(session.id, {"model_from_role": None})

    restored = Session.load(session.id, work_dir=tmp_path)
    clients = handler._ensure_session_llm_clients(restored).clients

    assert restored.model_from_role is False
    assert isinstance(clients.main, FallbackLLMClient)
    assert [candidate.selector for candidate in clients.main.candidates] == ["gpt-6.1-sol:max@openrouter"]


def test_model_switch_clears_role_source_even_with_live_sub_agent_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config_with_role_chain()
    monkeypatch.setattr("klaude_code.agent.runtime.config_ops.load_config", lambda: config)
    monkeypatch.setattr(agent_ops_module, "load_config", lambda: config)
    session = _sub_agent_session(tmp_path)
    session.agent_type = "code-reviewer"
    agent = Agent(
        session=session,
        profile=_StubProfileProvider().build_profile(_StubClient("initial"), work_dir=tmp_path),
    )
    switcher = ModelSwitcher(_StubProfileProvider())
    asyncio.run(switcher.change_model(agent, model_name="gpt-6.1-sol:max", save_as_default=False))
    session.ensure_meta_exists()

    assert session.model_from_role is False
    for selected in (session, Session.load(session.id, work_dir=tmp_path)):
        candidates = agent_ops_module._session_model_candidates(selected, config).candidates
        assert [candidate.selector for candidate in candidates] == ["gpt-6.1-sol:max@openrouter"]


def test_fork_of_role_session_keeps_parent_selector_without_role_source(tmp_path: Path) -> None:
    session = _sub_agent_session(tmp_path)
    session.agent_type = "code-reviewer"
    session.model_config_name = "gpt-6.1-sol:max"

    forked = session.fork()
    forked.ensure_meta_exists()
    restored = Session.load(forked.id, work_dir=tmp_path)

    assert restored.model_config_name == session.model_config_name
    assert restored.model_from_role is False
    candidates = agent_ops_module._session_model_candidates(restored, _config_with_role_chain()).candidates
    assert [candidate.selector for candidate in candidates] == ["gpt-6.1-sol:max@openrouter"]


def test_session_model_that_no_longer_resolves_reports_the_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The session model replaced by the config default must reach the client.

    Silently running another model is the bug: the session keeps its own model
    while it resolves, so the switch has to be stated.
    """
    handler, _actor = _handler("startup-model")
    monkeypatch.setattr(agent_ops_module, "load_config", lambda: _config_with_main_model("switched-model"))

    session = Session(work_dir=tmp_path)
    session.model_config_name = "gone-model"
    result = handler._ensure_session_llm_clients(session)

    assert result.clients.main.get_llm_config().model_id == "switched-model-id"
    warn = result.model_fallback_warn
    assert warn is not None
    assert warn.session_id == session.id
    assert (warn.from_model, warn.from_provider) == ("gone-model", None)
    assert (warn.to_model, warn.to_provider) == ("switched-model", "test-provider")
    assert warn.reason == "Unknown model: gone-model"
    assert warn.sub_agent_type is None


def test_blank_session_model_inherits_silently(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`PUT /model/config` clears the override with a blank selector.

    Clearing is the normal "inherit the config default" path, not a model that
    failed to resolve.
    """
    handler, _actor = _handler("startup-model")
    monkeypatch.setattr(agent_ops_module, "load_config", lambda: _config_with_main_model("switched-model"))

    session = Session(work_dir=tmp_path)
    session.model_config_name = "   "
    result = handler._ensure_session_llm_clients(session)

    assert result.clients.main_model_alias == "switched-model"
    assert result.model_fallback_warn is None


def test_session_model_reports_the_provider_it_was_pinned_to(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A qualified selector names its provider, which is often why it failed."""
    handler, _actor = _handler("startup-model")
    monkeypatch.setattr(agent_ops_module, "load_config", lambda: _config_with_main_model("switched-model"))

    session = Session(work_dir=tmp_path)
    session.model_config_name = "gone-model@gone-provider"
    warn = handler._ensure_session_llm_clients(session).model_fallback_warn

    assert warn is not None
    assert (warn.from_model, warn.from_provider) == ("gone-model", "gone-provider")
    assert warn.reason == "Unknown model: gone-model@gone-provider"


def test_restored_sub_agent_session_keeps_its_role_label(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """sub_agent_state is not persisted, so the role has to come from agent_type."""
    handler, _actor = _handler("startup-model")
    monkeypatch.setattr(agent_ops_module, "load_config", lambda: _config_with_main_model("switched-model"))

    session = Session(work_dir=tmp_path)
    session.agent_type = "code-reviewer"
    session.model_config_name = "gone-model"
    warn = handler._ensure_session_llm_clients(session).model_fallback_warn

    assert warn is not None
    assert warn.sub_agent_type == "code-reviewer"


def test_session_without_its_own_model_reports_no_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Inheriting the config default is the normal path, not a fallback."""
    handler, _actor = _handler("startup-model")
    monkeypatch.setattr(agent_ops_module, "load_config", lambda: _config_with_main_model("switched-model"))

    session = Session(work_dir=tmp_path)
    result = handler._ensure_session_llm_clients(session)

    assert result.clients.main_model_alias == "switched-model"
    assert result.model_fallback_warn is None


def test_resolved_session_model_reports_no_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    handler, _actor = _handler("startup-model")
    monkeypatch.setattr(agent_ops_module, "load_config", lambda: _config_with_extra_model("pinned-model"))

    session = Session(work_dir=tmp_path)
    session.model_config_name = "pinned-model"
    result = handler._ensure_session_llm_clients(session)

    assert result.clients.main.get_llm_config().model_id == "pinned-model-id"
    assert result.model_fallback_warn is None


def test_sub_agent_session_emits_the_fallback_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Warn after TaskStart makes the child visible, and only on its first turn."""

    async def _test() -> None:
        emitted: list[Any] = []
        handler, actor = _handler("startup-model", emitted=emitted, profile_provider=_StubProfileProvider())
        monkeypatch.setattr(agent_ops_module, "load_config", lambda: _config_with_main_model("switched-model"))

        session = _sub_agent_session(tmp_path)
        session.parent_session_id = "parent-id"
        session.model_config_name = "gone-model"
        agent = await handler.init_sub_agent_session(session)

        assert not emitted
        monkeypatch.setattr(handler, "_get_session_actor", lambda _sid: actor)
        monkeypatch.setattr(handler, "_schedule_prompt_suggestion", lambda _agent: None)

        async def run_task(self: Agent, *_args: Any, **_kwargs: Any) -> AsyncGenerator[events.Event]:
            yield events.TaskStartEvent(session_id=self.session.id, parent_session_id=self.session.parent_session_id)
            yield events.TaskFinishEvent(session_id=self.session.id, task_result="done")

        monkeypatch.setattr(Agent, "run_task", run_task)
        for _ in range(2):
            await handler._run_agent_task(agent, message.UserInputPayload(text="review"), "task-id", session.id)

        warns = [event for event in emitted if isinstance(event, events.FallbackModelConfigWarnEvent)]
        assert len(warns) == 1
        assert warns[0].session_id == session.id
        assert warns[0].sub_agent_type == "code-reviewer"
        assert (warns[0].from_model, warns[0].to_model) == ("gone-model", "switched-model")
        assert isinstance(emitted[0], events.TaskStartEvent)
        assert emitted[0].parent_session_id == "parent-id"
        assert emitted[1] is warns[0]
        assert not any(isinstance(event, events.ErrorEvent) for event in emitted)

        again = handler._ensure_session_llm_clients(session)
        assert again.clients is actor.clients
        assert again.model_fallback_warn is None

    asyncio.run(_test())


def test_main_session_emits_the_fallback_without_a_sub_agent_label(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _test() -> None:
        emitted: list[Any] = []
        handler, _actor = _handler("startup-model", emitted=emitted, profile_provider=_StubProfileProvider())
        monkeypatch.setattr(agent_ops_module, "load_config", lambda: _config_with_main_model("switched-model"))

        session = Session.create(work_dir=tmp_path)
        session.model_config_name = "gone-model"
        session.ensure_meta_exists()
        await handler.ensure_agent(session.id, work_dir=tmp_path, suppress_welcome=True, defer_replay=True)

        warns = [event for event in emitted if isinstance(event, events.FallbackModelConfigWarnEvent)]
        assert len(warns) == 1
        assert warns[0].session_id == session.id
        assert warns[0].sub_agent_type is None

    asyncio.run(_test())
