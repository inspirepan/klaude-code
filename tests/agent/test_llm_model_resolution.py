from __future__ import annotations

import pytest

from klaude_code.agent.runtime import llm
from klaude_code.agent.runtime.llm import (
    FallbackLLMClient,
    ModelResolutionError,
    build_llm_clients,
    collect_model_config_warnings,
)
from klaude_code.config.config import Config, ModelConfig, ProviderConfig
from klaude_code.protocol import llm_param


def _provider() -> ProviderConfig:
    return ProviderConfig(
        provider_name="codex",
        protocol=llm_param.LLMClientProtocol.OPENAI,
        api_key="test-key",
        model_list=[
            ModelConfig(model_name="gpt-6-sol", model_id="gpt-6-sol"),
            ModelConfig(model_name="gpt-6-luna", model_id="gpt-6-luna"),
        ],
    )


@pytest.fixture
def builtin(monkeypatch: pytest.MonkeyPatch) -> Config:
    defaults = Config(
        main_model="gpt-6-sol@codex",
        fast_model="gpt-6-luna@codex",
        sub_agent_models={"finder": "gpt-6-luna@codex"},
    )
    monkeypatch.setattr(llm, "get_builtin_config", lambda: defaults)
    return defaults


@pytest.mark.usefixtures("builtin")
def test_removed_sub_agent_model_falls_back_to_builtin_with_warning() -> None:
    config = Config(
        provider_list=[_provider()],
        main_model="gpt-6-sol@codex",
        sub_agent_models={"finder": "gpt-5.6-luna@codex"},
    )

    clients = build_llm_clients(config)

    finder = clients.sub_clients["finder"]
    assert isinstance(finder, FallbackLLMClient)
    assert finder.candidates[0].selector == "gpt-6-luna@codex"
    assert len(clients.warnings) == 1
    assert "sub_agent_models.finder 'gpt-5.6-luna@codex'" in clients.warnings[0]
    assert "gpt-6-luna@codex" in clients.warnings[0]


@pytest.mark.usefixtures("builtin")
def test_removed_fast_and_compact_models_do_not_fail() -> None:
    config = Config(
        provider_list=[_provider()],
        main_model="gpt-6-sol@codex",
        fast_model="gpt-5.6-luna@codex",
        compact_model="gpt-5.6-luna@codex",
    )

    clients = build_llm_clients(config, skip_sub_agents=True)

    assert clients.fast is not None
    assert clients.fast.model_name == "gpt-6-luna"
    # No builtin compact default: the role inherits the main model.
    assert clients.compact is None
    assert [warning.split(" ", 1)[0] for warning in clients.warnings] == ["fast_model", "compact_model"]


@pytest.mark.usefixtures("builtin")
def test_removed_main_model_falls_back_but_explicit_override_fails() -> None:
    config = Config(provider_list=[_provider()], main_model="gpt-5.6-luna@codex")

    clients = build_llm_clients(config, skip_sub_agents=True)
    assert clients.main_model_alias == "gpt-6-sol@codex"
    assert clients.warnings and clients.warnings[0].startswith("main_model 'gpt-5.6-luna@codex'")

    with pytest.raises(ModelResolutionError):
        build_llm_clients(config, model_override="gpt-5.6-luna@codex", skip_sub_agents=True)


def test_unavailable_builtin_default_stays_silent(builtin: Config) -> None:
    builtin.sub_agent_models = {"finder": "missing@nowhere"}
    config = Config(
        provider_list=[_provider()],
        main_model="gpt-6-sol@codex",
        sub_agent_models={"finder": "missing@nowhere"},
    )

    clients = build_llm_clients(config)

    assert "finder" not in clients.sub_clients
    assert collect_model_config_warnings(config) == []
