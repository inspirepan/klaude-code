"""Tests for sub-agent model helper behavior and image-model availability helpers."""

from __future__ import annotations

from klaude_code.config.config import Config, ModelConfig, ProviderConfig
from klaude_code.config.sub_agent_model_helper import SubAgentModelHelper
from klaude_code.protocol import llm_param


class TestImageModelAvailability:
    def test_has_available_image_model_returns_true_when_image_model_exists(self) -> None:
        provider = ProviderConfig(
            provider_name="test-provider",
            protocol=llm_param.LLMClientProtocol.OPENAI,
            api_key="test-key",
            model_list=[
                ModelConfig(
                    model_name="image-model",
                    model_id="test-image-model",
                    modalities=["image", "text"],
                ),
            ],
        )
        config = Config(provider_list=[provider])

        assert config.has_available_image_model() is True

    def test_has_available_image_model_ignores_disabled_image_models(self) -> None:
        provider = ProviderConfig(
            provider_name="test-provider",
            protocol=llm_param.LLMClientProtocol.OPENAI,
            api_key="test-key",
            model_list=[
                ModelConfig(
                    model_name="image-model",
                    model_id="test-image-model",
                    modalities=["image", "text"],
                    disabled=True,
                ),
            ],
        )
        config = Config(provider_list=[provider])

        assert config.has_available_image_model() is False

    def test_get_first_available_image_model_returns_model_name(self) -> None:
        provider = ProviderConfig(
            provider_name="test-provider",
            protocol=llm_param.LLMClientProtocol.OPENAI,
            api_key="test-key",
            model_list=[
                ModelConfig(
                    model_name="text-model",
                    model_id="gpt-4",
                ),
                ModelConfig(
                    model_name="nano-banana-pro",
                    model_id="image-gen-model",
                    modalities=["image", "text"],
                ),
            ],
        )
        config = Config(provider_list=[provider])

        assert config.get_first_available_image_model() == "nano-banana-pro"


class TestSubAgentModelHelper:
    def test_task_defaults_to_main_model(self) -> None:
        config = Config(provider_list=[])
        helper = SubAgentModelHelper(config)

        result = helper.describe_empty_model_config_behavior("Task", main_model_name="anthropic/test")
        assert result.description == "use default behavior: anthropic/test"
        assert result.resolved_model_name == "anthropic/test"

    def test_available_sub_agents_only_task_and_explore(self) -> None:
        config = Config(provider_list=[])
        helper = SubAgentModelHelper(config)

        sub_agents = helper.get_available_sub_agents()
        names = {sa.profile.name for sa in sub_agents}
        assert names == {"Task", "Explore"}

    def test_selectable_models_are_not_filtered_by_image_requirement(self) -> None:
        provider = ProviderConfig(
            provider_name="test-provider",
            protocol=llm_param.LLMClientProtocol.OPENAI,
            api_key="test-key",
            model_list=[
                ModelConfig(
                    model_name="image-model",
                    model_id="img",
                    modalities=["image", "text"],
                ),
                ModelConfig(
                    model_name="text-model",
                    model_id="txt",
                ),
            ],
        )
        config = Config(provider_list=[provider])
        helper = SubAgentModelHelper(config)

        models = helper.get_selectable_models("Task")
        names = [m.model_name for m in models]
        assert names == ["image-model", "text-model"]
