from __future__ import annotations

from typing import Any

from klaude_code.cli.agents_cmd import build_agent_inventory, build_json_inventory, build_prime_guide
from klaude_code.cli.list_model import _build_model_rows
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


def test_json_inventory_shape() -> None:
    inventory = build_json_inventory(_config())
    assert set(inventory) == {"agent_types", "models", "defaults"}
    assert inventory["defaults"]["main_model"] == "sonnet"
    assert isinstance(inventory["defaults"]["headless_max_running"], int)


def test_prime_guide_mentions_core_loop_and_inventory() -> None:
    guide = build_prime_guide(_config())
    for needle in (
        "klaude run",
        "klaude wait",
        "klaude output",
        "klaude respond",
        "--group",
        "Exit codes",
        "finder",
        "needs_you",
        "--any",
        "without checking the directory",
        "trusted directories",
    ):
        assert needle in guide, f"prime guide is missing: {needle}"
