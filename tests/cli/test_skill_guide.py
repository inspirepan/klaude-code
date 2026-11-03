from __future__ import annotations

from typing import Any

import pytest
from typer.testing import CliRunner

from klaude_code.cli.list_model import _build_model_rows
from klaude_code.cli.main import app
from klaude_code.cli.skill_guide import build_agent_guide, build_agent_inventory
from klaude_code.config import Config
from klaude_code.config.config import ModelConfig, ProviderConfig
from klaude_code.protocol import llm_param


def _config(sub_agent_models: dict[str, Any] | None = None) -> Config:
    return Config(
        provider_list=[
            ProviderConfig(
                provider_name="test-provider",
                protocol=llm_param.LLMClientProtocol.ANTHROPIC,
                api_key="test-key",
                model_list=[
                    ModelConfig(model_name="sonnet", model_id="sonnet"),
                    ModelConfig(model_name="flash", model_id="flash"),
                ],
            )
        ],
        main_model="sonnet",
        sub_agent_models={"finder": "flash"} if sub_agent_models is None else sub_agent_models,
    )


def test_agent_inventory_includes_main_and_profiles() -> None:
    rows = build_agent_inventory(_config())
    names = [row["name"] for row in rows]
    assert names[0] == "main"
    assert "finder" in names
    assert "code-reviewer" in names
    finder = next(row for row in rows if row["name"] == "finder")
    assert finder["model"] == "flash"
    assert finder["model_note"] == ""


def test_unavailable_configured_model_reports_the_fallback() -> None:
    config = _config({"finder": "flash", "code-reviewer": ["gpt-6.1-sol:max", "opus"]})

    rows = build_agent_inventory(config)
    reviewer = next(row for row in rows if row["name"] == "code-reviewer")

    # The runtime hands the child the parent's model when nothing in the configured
    # chain is available, so the inventory must report the effective model.
    assert reviewer["model"] == "sonnet"
    assert reviewer["model_note"] == "configured 'gpt-6.1-sol:max > opus' is unavailable"


def test_model_table_tags_fallback_roles_on_the_main_model() -> None:
    config = _config({"finder": "flash", "code-reviewer": ["gpt-6.1-sol:max", "opus"]})

    rows = _build_model_rows(config.provider_list[0], config)
    trailing = {alias.plain: note.plain for alias, _, note in rows}

    assert trailing["flash"] == "finder"
    assert trailing["sonnet"] == "main · code-reviewer (fallback)"


def test_model_table_attributes_roles_to_the_model_that_runs() -> None:
    """A main_model chain may start with a model only an unusable provider defines.

    The role tags belong on the row the table prints and the runtime uses, not on
    the filtered-out row of the provider that cannot serve it.
    """

    def _provider(name: str, model: str, api_key: str | None) -> ProviderConfig:
        return ProviderConfig(
            provider_name=name,
            protocol=llm_param.LLMClientProtocol.OPENAI,
            api_key=api_key,
            model_list=[ModelConfig(model_name=model, model_id=model)],
        )

    config = Config(
        provider_list=[
            _provider("keyless", "gpt-6.1-sol:max", None),
            _provider("usable", "opus", "test-key"),
        ],
        main_model=["gpt-6.1-sol:max", "opus"],
        sub_agent_models={"code-reviewer": ["gone-model", "also-gone"]},
    )

    rows = _build_model_rows(config.provider_list[1], config)
    trailing = {alias.plain: note.plain for alias, _, note in rows}

    assert trailing["opus"] == "main · code-reviewer (fallback)"


def test_agent_guide_mentions_core_loop_and_inventory() -> None:
    guide = build_agent_guide(_config())
    for needle in (
        "klaude run",
        "klaude wait",
        "klaude output",
        "klaude respond",
        "klaude interrupt",
        "klaude unpause",
        "--group",
        "Exit codes",
        "finder",
        "needs_you",
        "--any",
        "without checking the directory",
        "trusted directories",
    ):
        assert needle in guide, f"agent guide is missing: {needle}"
    assert "klaude kill" not in guide
    assert "klaude resume" not in guide


def test_skill_flag_prints_guide_without_runtime_or_tty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("klaude_code.cli.skill_guide._load_config_or_exit", _config)

    def unexpected(*_a: Any, **_k: Any) -> None:
        pytest.fail("--skill must not start a Runtime or access online sessions")

    monkeypatch.setattr("klaude_code.cli.headless_cmd._fetch_rows", unexpected)
    monkeypatch.setattr("klaude_code.app.runtime.initialize_app_components", unexpected)
    result = CliRunner().invoke(app, ["--skill"])
    assert result.exit_code == 0, result.output
    assert result.output.startswith("# Driving klaude from another agent")
    assert "finder" in result.output and "klaude run" in result.output


def test_help_points_agents_to_skill_flag() -> None:
    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "Agent? Run: klaude --skill" in result.output
    assert "--prime" not in result.output


def test_available_models_list_only_invokable_names() -> None:
    guide = build_agent_guide(_config())
    models = guide.split("## Available models\n", 1)[1]
    assert "- `sonnet@test-provider`" in models
    assert "- `flash@test-provider`" in models
    assert "→" not in models
    assert "Model aliases" not in guide


def test_removed_agents_command_is_not_registered() -> None:
    result = CliRunner().invoke(app, ["agents"])
    assert result.exit_code == 2
    assert "No such command" in result.output
