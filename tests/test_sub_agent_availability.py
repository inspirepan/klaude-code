"""Tests for sub-agent availability based on model requirements."""

from __future__ import annotations

from klaude_code.config.config import Config, ModelConfig, ProviderConfig
from klaude_code.config.sub_agent_model_helper import SubAgentModelHelper
from klaude_code.core.agent_profile import load_agent_tools
from klaude_code.protocol import llm_param
from klaude_code.protocol.sub_agent import AVAILABILITY_IMAGE_MODEL


def _check_availability_requirement(requirement: str | None, config: Config | None) -> bool:
    """Test helper that wraps SubAgentModelHelper.check_availability_requirement."""
    if requirement is None or config is None:
        return True
    helper = SubAgentModelHelper(config)
    return helper.check_availability_requirement(requirement)


class TestImageModelAvailability:
    """Tests for image model availability detection."""

    def test_has_available_image_model_returns_true_when_image_model_exists(self) -> None:
        """Config with an image model should return True."""
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
        """Disabled image models should not be considered available."""
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

    def test_has_available_image_model_returns_false_when_no_image_model(self) -> None:
        """Config without image model should return False."""
        provider = ProviderConfig(
            provider_name="test-provider",
            protocol=llm_param.LLMClientProtocol.OPENAI,
            api_key="test-key",
            model_list=[
                ModelConfig(
                    model_name="text-model",
                    model_id="gpt-4",
                ),
            ],
        )
        config = Config(provider_list=[provider])

        assert config.has_available_image_model() is False

    def test_has_available_image_model_returns_false_when_provider_unavailable(self) -> None:
        """Image model with missing API key should not be considered available."""
        provider = ProviderConfig(
            provider_name="test-provider",
            protocol=llm_param.LLMClientProtocol.OPENAI,
            api_key=None,  # No API key
            model_list=[
                ModelConfig(
                    model_name="image-model",
                    model_id="test-image-model",
                    modalities=["image", "text"],
                ),
            ],
        )
        config = Config(provider_list=[provider])

        assert config.has_available_image_model() is False

    def test_get_first_available_image_model_returns_model_name(self) -> None:
        """Should return the first available image model name."""
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

    def test_get_first_available_image_model_skips_disabled_models(self) -> None:
        """Should skip disabled image models when selecting the first available."""
        provider = ProviderConfig(
            provider_name="test-provider",
            protocol=llm_param.LLMClientProtocol.OPENAI,
            api_key="test-key",
            model_list=[
                ModelConfig(
                    model_name="nano-banana-pro",
                    model_id="image-gen-model",
                    modalities=["image", "text"],
                    disabled=True,
                ),
                ModelConfig(
                    model_name="image-model-2",
                    model_id="image-gen-model-2",
                    modalities=["image", "text"],
                ),
            ],
        )
        config = Config(provider_list=[provider])

        assert config.get_first_available_image_model() == "image-model-2"

    def test_get_first_available_image_model_returns_none_when_unavailable(self) -> None:
        """Should return None when no image model is available."""
        provider = ProviderConfig(
            provider_name="test-provider",
            protocol=llm_param.LLMClientProtocol.OPENAI,
            api_key="test-key",
            model_list=[
                ModelConfig(
                    model_name="text-model",
                    model_id="gpt-4",
                ),
            ],
        )
        config = Config(provider_list=[provider])

        assert config.get_first_available_image_model() is None


class TestCheckAvailabilityRequirement:
    """Tests for _check_availability_requirement function."""

    def test_returns_true_when_no_requirement(self) -> None:
        """Should return True when requirement is None."""
        config = Config(provider_list=[])
        assert _check_availability_requirement(None, config) is True

    def test_returns_true_when_no_config(self) -> None:
        """Should return True when config is None."""
        assert _check_availability_requirement(AVAILABILITY_IMAGE_MODEL, None) is True

    def test_returns_true_when_image_model_available(self) -> None:
        """Should return True when image model is available."""
        provider = ProviderConfig(
            provider_name="test",
            protocol=llm_param.LLMClientProtocol.OPENAI,
            api_key="test-key",
            model_list=[
                ModelConfig(
                    model_name="image-model",
                    model_id="img",
                    modalities=["image", "text"],
                ),
            ],
        )
        config = Config(provider_list=[provider])

        assert _check_availability_requirement(AVAILABILITY_IMAGE_MODEL, config) is True

    def test_returns_false_when_only_image_model_is_disabled(self) -> None:
        provider = ProviderConfig(
            provider_name="test",
            protocol=llm_param.LLMClientProtocol.OPENAI,
            api_key="test-key",
            model_list=[
                ModelConfig(
                    model_name="image-model",
                    model_id="img",
                    modalities=["image", "text"],
                    disabled=True,
                ),
            ],
        )
        config = Config(provider_list=[provider])

        assert _check_availability_requirement(AVAILABILITY_IMAGE_MODEL, config) is False

    def test_returns_false_when_image_model_unavailable(self) -> None:
        """Should return False when no image model is available."""
        provider = ProviderConfig(
            provider_name="test",
            protocol=llm_param.LLMClientProtocol.OPENAI,
            api_key="test-key",
            model_list=[
                ModelConfig(
                    model_name="text-model",
                    model_id="gpt-4",
                ),
            ],
        )
        config = Config(provider_list=[provider])

        assert _check_availability_requirement(AVAILABILITY_IMAGE_MODEL, config) is False

    def test_returns_true_for_unknown_requirement(self) -> None:
        """Should return True for unknown requirements (assume available)."""
        config = Config(provider_list=[])
        assert _check_availability_requirement("unknown_requirement", config) is True


class TestLoadAgentToolsWithAvailability:
    """Tests for load_agent_tools with availability filtering."""

    def test_imagegen_included_when_image_model_available(self) -> None:
        """ImageGen tool should be included when image model is available."""
        provider = ProviderConfig(
            provider_name="test",
            protocol=llm_param.LLMClientProtocol.OPENAI,
            api_key="test-key",
            model_list=[
                ModelConfig(
                    model_name="image-model",
                    model_id="img",
                    modalities=["image", "text"],
                ),
            ],
        )
        config = Config(provider_list=[provider])

        tools = load_agent_tools("claude-sonnet", config=config)
        tool_names = [t.name for t in tools]

        assert "ImageGen" in tool_names

    def test_imagegen_excluded_when_image_model_unavailable(self) -> None:
        """ImageGen tool should be excluded when no image model is available."""
        provider = ProviderConfig(
            provider_name="test",
            protocol=llm_param.LLMClientProtocol.OPENAI,
            api_key="test-key",
            model_list=[
                ModelConfig(
                    model_name="text-model",
                    model_id="gpt-4",
                ),
            ],
        )
        config = Config(provider_list=[provider])

        tools = load_agent_tools("claude-sonnet", config=config)
        tool_names = [t.name for t in tools]

        assert "ImageGen" not in tool_names

    def test_imagegen_excluded_when_only_image_model_is_disabled(self) -> None:
        """ImageGen tool should be excluded when the only image model is disabled."""
        provider = ProviderConfig(
            provider_name="test",
            protocol=llm_param.LLMClientProtocol.OPENAI,
            api_key="test-key",
            model_list=[
                ModelConfig(
                    model_name="image-model",
                    model_id="img",
                    modalities=["image", "text"],
                    disabled=True,
                ),
            ],
        )
        config = Config(provider_list=[provider])

        tools = load_agent_tools("claude-sonnet", config=config)
        tool_names = [t.name for t in tools]

        assert "ImageGen" not in tool_names

    def test_other_subagents_not_affected_by_image_availability(self) -> None:
        """Task should be included regardless of image model availability."""
        provider = ProviderConfig(
            provider_name="test",
            protocol=llm_param.LLMClientProtocol.OPENAI,
            api_key="test-key",
            model_list=[
                ModelConfig(
                    model_name="text-model",
                    model_id="gpt-4",
                ),
            ],
        )
        config = Config(provider_list=[provider])

        tools = load_agent_tools("claude-sonnet", config=config)
        tool_names = [t.name for t in tools]

        assert "Task" in tool_names
        assert "Explore" not in tool_names
        assert "Web" not in tool_names

    def test_imagegen_excluded_when_no_config_provided(self) -> None:
        """When config is None, ImageGen should still be included (backward compatibility)."""
        # This tests the case where config is not provided at all
        tools = load_agent_tools("claude-sonnet", config=None)
        tool_names = [t.name for t in tools]

        # Without config, we cannot check availability, so ImageGen is included
        assert "ImageGen" in tool_names


class TestEmptyModelConfigBehavior:
    """Tests for user-facing behavior of an unset sub-agent model config."""

    def test_task_defaults_to_main_model(self) -> None:
        config = Config(provider_list=[])
        helper = SubAgentModelHelper(config)

        result = helper.describe_empty_model_config_behavior("Task", main_model_name="anthropic/test")
        assert result.description == "use default behavior: anthropic/test"
        assert result.resolved_model_name == "anthropic/test"

    def test_imagegen_defaults_to_first_available_image_model(self) -> None:
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
        helper = SubAgentModelHelper(config)

        result = helper.describe_empty_model_config_behavior("ImageGen", main_model_name="anthropic/test")
        assert result.description == "auto-select first available image model: nano-banana-pro"
        assert result.resolved_model_name == "nano-banana-pro"

        assert helper.resolve_default_model_override("Task") is None
        assert helper.resolve_default_model_override("ImageGen") == "nano-banana-pro"

    def test_imagegen_default_ignores_disabled_image_models(self) -> None:
        provider = ProviderConfig(
            provider_name="test-provider",
            protocol=llm_param.LLMClientProtocol.OPENAI,
            api_key="test-key",
            model_list=[
                ModelConfig(
                    model_name="nano-banana-pro",
                    model_id="image-gen-model",
                    modalities=["image", "text"],
                    disabled=True,
                ),
            ],
        )
        config = Config(provider_list=[provider])
        helper = SubAgentModelHelper(config)

        result = helper.describe_empty_model_config_behavior("ImageGen", main_model_name="anthropic/test")
        assert result.description == "auto-select first available image model"
        assert result.resolved_model_name is None


class TestSubAgentModelInfo:
    """Tests for SubAgentModelHelper.get_available_sub_agents output."""

    def test_get_available_sub_agents_marks_configured_vs_effective_models(self) -> None:
        provider = ProviderConfig(
            provider_name="test-provider",
            protocol=llm_param.LLMClientProtocol.OPENAI,
            api_key="test-key",
            model_list=[
                ModelConfig(
                    model_name="nano-banana-pro",
                    model_id="image-gen-model",
                    modalities=["image", "text"],
                ),
            ],
        )
        config = Config(provider_list=[provider])
        helper = SubAgentModelHelper(config)

        sub_agents = helper.get_available_sub_agents()
        by_name = {sa.profile.name: sa for sa in sub_agents}

        assert by_name["Task"].configured_model is None
        assert by_name["Task"].effective_model is None

        assert by_name["ImageGen"].configured_model is None
        assert by_name["ImageGen"].effective_model == "nano-banana-pro"

    def test_get_available_sub_agents_excludes_imagegen_when_only_image_model_disabled(self) -> None:
        provider = ProviderConfig(
            provider_name="test-provider",
            protocol=llm_param.LLMClientProtocol.OPENAI,
            api_key="test-key",
            model_list=[
                ModelConfig(
                    model_name="nano-banana-pro",
                    model_id="image-gen-model",
                    modalities=["image", "text"],
                    disabled=True,
                ),
            ],
        )
        config = Config(provider_list=[provider])
        helper = SubAgentModelHelper(config)

        sub_agents = helper.get_available_sub_agents()
        by_name = {sa.profile.name: sa for sa in sub_agents}

        assert "ImageGen" not in by_name


class TestSelectableModels:
    """Tests for SubAgentModelHelper.get_selectable_models filtering."""

    def test_get_selectable_models_excludes_disabled_models(self) -> None:
        provider = ProviderConfig(
            provider_name="test-provider",
            protocol=llm_param.LLMClientProtocol.OPENAI,
            api_key="test-key",
            model_list=[
                ModelConfig(
                    model_name="text-model",
                    model_id="gpt-4",
                    disabled=True,
                ),
                ModelConfig(
                    model_name="text-model-2",
                    model_id="gpt-4-2",
                ),
            ],
        )
        config = Config(provider_list=[provider])
        helper = SubAgentModelHelper(config)

        models = helper.get_selectable_models("Task")
        names = [m.model_name for m in models]

        assert names == ["text-model-2"]

    def test_get_selectable_models_for_imagegen_excludes_disabled_image_models(self) -> None:
        provider = ProviderConfig(
            provider_name="test-provider",
            protocol=llm_param.LLMClientProtocol.OPENAI,
            api_key="test-key",
            model_list=[
                ModelConfig(
                    model_name="image-model-1",
                    model_id="img-1",
                    modalities=["image", "text"],
                    disabled=True,
                ),
                ModelConfig(
                    model_name="image-model-2",
                    model_id="img-2",
                    modalities=["image", "text"],
                ),
                ModelConfig(
                    model_name="text-only",
                    model_id="txt",
                ),
            ],
        )
        config = Config(provider_list=[provider])
        helper = SubAgentModelHelper(config)

        models = helper.get_selectable_models("ImageGen")
        names = [m.model_name for m in models]

        assert names == ["image-model-2"]
