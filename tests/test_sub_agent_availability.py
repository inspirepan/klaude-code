"""Tests for sub-agent model helper behavior."""

from __future__ import annotations

from klaude_code.config.config import Config, ModelConfig, ProviderConfig
from klaude_code.config.sub_agent_model_helper import SubAgentModelHelper
from klaude_code.protocol import llm_param


class TestSubAgentModelHelper:
    def test_task_defaults_to_main_model(self) -> None:
        config = Config(provider_list=[])
        helper = SubAgentModelHelper(config)

        result = helper.describe_empty_model_config_behavior("Task", main_model_name="anthropic/test")
        assert result.description == "use default behavior: anthropic/test"
        assert result.resolved_model_name == "anthropic/test"

    def test_explore_defaults_to_main_model(self) -> None:
        config = Config(provider_list=[])
        helper = SubAgentModelHelper(config)

        result = helper.describe_empty_model_config_behavior("Explore", main_model_name="anthropic/test")
        assert result.description == "use default behavior: anthropic/test"
        assert result.resolved_model_name == "anthropic/test"

    def test_available_sub_agents_only_task_and_explore(self) -> None:
        config = Config(provider_list=[])
        helper = SubAgentModelHelper(config)

        sub_agents = helper.get_available_sub_agents()
        names = {sa.profile.name for sa in sub_agents}
        assert names == {"Task", "Explore"}

    def test_selectable_models_returns_all_available_models(self) -> None:
        provider = ProviderConfig(
            provider_name="test-provider",
            protocol=llm_param.LLMClientProtocol.OPENAI,
            api_key="test-key",
            model_list=[
                ModelConfig(
                    model_name="model-a",
                    model_id="a",
                ),
                ModelConfig(
                    model_name="model-b",
                    model_id="b",
                ),
            ],
        )
        config = Config(provider_list=[provider])
        helper = SubAgentModelHelper(config)

        models = helper.get_selectable_models("Task")
        names = [m.model_name for m in models]
        assert names == ["model-a", "model-b"]

    def test_role_override_used_when_present(self) -> None:
        config = Config(
            provider_list=[],
            sub_agent_models={
                "general-purpose": "model-task",
                "explore": "model-explore",
            },
        )
        helper = SubAgentModelHelper(config)

        task_behavior = helper.describe_empty_model_config_behavior("Task", main_model_name="main")
        explore_behavior = helper.describe_empty_model_config_behavior("Explore", main_model_name="main")

        assert task_behavior.resolved_model_name == "model-task"
        assert explore_behavior.resolved_model_name == "model-explore"

    def test_build_sub_agent_client_configs_only_for_explicit_roles(self) -> None:
        config = Config(provider_list=[], sub_agent_models={"general-purpose": "model-task"})
        helper = SubAgentModelHelper(config)

        result = helper.build_sub_agent_client_configs()
        assert result == {"Task": "model-task"}
