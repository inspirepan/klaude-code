"""Tests for the config module."""

import asyncio

# Import config module directly without triggering __init__.py
import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

# Avoid circular import by importing protocol first
from klaude_code.protocol import llm_param

_config_spec = importlib.util.spec_from_file_location(
    "config_module",
    Path(__file__).parent.parent / "src" / "klaude_code" / "config" / "config.py",
)
assert _config_spec is not None and _config_spec.loader is not None
_config_module = importlib.util.module_from_spec(_config_spec)
sys.modules["config_module"] = _config_module
_config_spec.loader.exec_module(_config_module)

Config = _config_module.Config
UserConfig = _config_module.UserConfig
ModelConfig = _config_module.ModelConfig
ProviderConfig = _config_module.ProviderConfig
UserProviderConfig = _config_module.UserProviderConfig
config_path = _config_module.config_path
load_config = _config_module.load_config


# =============================================================================
# mask_api_key function - copied here to avoid circular import issues
# =============================================================================


def mask_api_key(api_key: str | None) -> str:
    """Mask API key to show only first 6 and last 6 characters with *** in between"""
    if not api_key or api_key == "N/A":
        return "N/A"

    if len(api_key) <= 12:
        return api_key

    return f"{api_key[:6]} ... {api_key[-6:]}"


# =============================================================================
# ModelConfig Tests
# =============================================================================


class TestModelConfig:
    """Tests for the ModelConfig dataclass."""

    def test_model_config_creation(self) -> None:
        """Test basic ModelConfig creation."""
        model_params = llm_param.LLMConfigModelParameter(
            model="gpt-4",
            max_tokens=8192,
        )
        config = ModelConfig(
            model_name="test-model",
            model_params=model_params,
        )

        assert config.model_name == "test-model"
        assert config.model_params.model == "gpt-4"
        assert config.model_params.max_tokens == 8192

    def test_model_config_with_thinking(self) -> None:
        """Test ModelConfig with thinking parameters."""
        thinking = llm_param.Thinking(
            reasoning_effort="high",
            reasoning_summary="auto",
            type="enabled",
        )
        model_params = llm_param.LLMConfigModelParameter(
            model="gpt-5",
            max_tokens=32000,
            thinking=thinking,
        )
        config = ModelConfig(
            model_name="gpt-5-high",
            model_params=model_params,
        )

        assert config.model_params.thinking is not None
        assert config.model_params.thinking.reasoning_effort == "high"
        assert config.model_params.thinking.reasoning_summary == "auto"
        assert config.model_params.thinking.type == "enabled"


# =============================================================================
# Config Tests
# =============================================================================


class TestConfig:
    """Tests for the Config dataclass."""

    @pytest.fixture
    def sample_provider(self, sample_model_config: ModelConfig) -> ProviderConfig:
        """Create a sample provider for testing."""
        return ProviderConfig(
            provider_name="test-provider",
            protocol=llm_param.LLMClientProtocol.OPENAI,
            api_key="test-api-key",
            base_url="https://api.example.com/v1",
            model_list=[sample_model_config],
        )

    @pytest.fixture
    def sample_model_config(self) -> ModelConfig:
        """Create a sample model config for testing."""
        return ModelConfig(
            model_name="test-model",
            model_params=llm_param.LLMConfigModelParameter(
                model="test-model-v1",
                max_tokens=4096,
            ),
        )

    @pytest.fixture
    def sample_config(self, sample_provider: ProviderConfig) -> Config:
        """Create a sample Config for testing."""
        return Config(
            provider_list=[sample_provider],
            main_model="test-model",
        )

    def test_config_creation(self, sample_config: Config) -> None:
        """Test basic Config creation."""
        assert sample_config.main_model == "test-model"
        assert len(sample_config.provider_list) == 1
        assert len(sample_config.iter_model_entries()) == 1
        assert sample_config.sub_agent_models == {}
        assert sample_config.theme is None

    def test_config_with_theme(self, sample_provider: ProviderConfig) -> None:
        """Test Config with theme."""
        config = Config(
            provider_list=[sample_provider],
            main_model="test-model",
            theme="dark",
        )
        assert config.theme == "dark"

    def test_get_model_config(self, sample_config: Config) -> None:
        """Test getting model config by name."""
        llm_config = sample_config.get_model_config("test-model")

        assert llm_config.model == "test-model-v1"
        assert llm_config.max_tokens == 4096
        assert llm_config.provider_name == "test-provider"
        assert llm_config.protocol == llm_param.LLMClientProtocol.OPENAI
        assert llm_config.api_key == "test-api-key"

    def test_get_model_config_unknown_model(self, sample_config: Config) -> None:
        """Test getting config for unknown model raises error."""
        with pytest.raises(ValueError, match="Unknown model: nonexistent-model"):
            sample_config.get_model_config("nonexistent-model")

    def test_get_model_config_missing_model_in_providers(self) -> None:
        """Test getting config for model missing from all providers raises error."""
        provider = ProviderConfig(
            provider_name="test-provider",
            protocol=llm_param.LLMClientProtocol.OPENAI,
            api_key="test-api-key",
            model_list=[],
        )
        config = Config(
            provider_list=[provider],
            main_model="orphan-model",
        )

        with pytest.raises(ValueError, match="Unknown model: orphan-model"):
            config.get_model_config("orphan-model")

    def test_sub_agent_models_normalization(self, sample_provider: ProviderConfig) -> None:
        """Test that sub_agent_models keys are normalized to canonical names."""
        # Use lowercase keys that should be normalized
        config = Config(
            provider_list=[sample_provider],
            main_model="test-model",
            sub_agent_models={"task": "model-a", "oracle": "model-b"},
        )

        # Keys should be normalized to canonical form (matching SubAgentProfile names)
        # Based on sub_agent.py, the canonical names are "Task", "Oracle", etc.
        assert "Task" in config.sub_agent_models
        assert "Oracle" in config.sub_agent_models
        assert config.sub_agent_models["Task"] == "model-a"
        assert config.sub_agent_models["Oracle"] == "model-b"

    def test_sub_agent_models_empty(self, sample_provider: ProviderConfig) -> None:
        """Test that empty sub_agent_models is handled correctly."""
        config = Config(
            provider_list=[sample_provider],
            main_model="test-model",
            sub_agent_models={},
        )
        assert config.sub_agent_models == {}

    def test_sub_agent_models_none(self, sample_provider: ProviderConfig) -> None:
        """Test that None sub_agent_models is handled correctly."""
        # Pass data through model_validate to trigger validator
        data: dict[str, Any] = {
            "provider_list": [sample_provider.model_dump()],
            "main_model": "test-model",
            "sub_agent_models": None,
        }
        config = Config.model_validate(data)
        assert config.sub_agent_models == {}


class TestConfigSave:
    """Tests for Config.save() method."""

    def test_save_config_only_saves_user_config(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that save only saves user config fields, not merged providers."""
        test_config_path = tmp_path / "test-config.yaml"
        monkeypatch.setattr(_config_module, "config_path", test_config_path)

        # Create a merged config with builtin providers
        provider = llm_param.LLMConfigProviderParameter(
            provider_name="builtin-provider",
            protocol=llm_param.LLMClientProtocol.OPENAI,
            api_key="test-key",
        )
        model = ModelConfig(
            model_name="builtin-model",
            model_params=llm_param.LLMConfigModelParameter(model="gpt-4"),
        )
        provider_config = ProviderConfig(**provider.model_dump(), model_list=[model])

        # Config without user_config reference (simulates merged config with only builtin)
        config = Config(
            provider_list=[provider_config],
            main_model="test-model",
        )

        asyncio.run(config.save())

        assert test_config_path.exists()
        saved_content = yaml.safe_load(test_config_path.read_text())
        # Only main_model should be saved, not the (builtin) provider_list
        assert saved_content["main_model"] == "test-model"
        assert "provider_list" not in saved_content

    def test_save_config_with_user_providers(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that save includes user-defined providers."""
        test_config_path = tmp_path / "test-config.yaml"
        monkeypatch.setattr(_config_module, "config_path", test_config_path)

        # Create user config with custom provider
        user_provider = UserProviderConfig(
            provider_name="my-custom-provider",
            protocol=llm_param.LLMClientProtocol.OPENAI,
            api_key="my-key",
            model_list=[
                ModelConfig(
                    model_name="my-model",
                    model_params=llm_param.LLMConfigModelParameter(model="custom-model"),
                )
            ],
        )
        user_config = UserConfig(
            main_model="my-model",
            provider_list=[user_provider],
        )

        # Create merged config with user_config reference
        full_provider = ProviderConfig(
            provider_name="my-custom-provider",
            protocol=llm_param.LLMClientProtocol.OPENAI,
            api_key="my-key",
            model_list=[
                ModelConfig(
                    model_name="my-model",
                    model_params=llm_param.LLMConfigModelParameter(model="custom-model"),
                )
            ],
        )
        config = Config(
            provider_list=[full_provider],
            main_model="my-model",
        )
        config.set_user_config(user_config)

        asyncio.run(config.save())

        assert test_config_path.exists()
        saved_content = yaml.safe_load(test_config_path.read_text())
        assert saved_content["main_model"] == "my-model"
        # User provider should be saved
        assert len(saved_content["provider_list"]) == 1
        assert saved_content["provider_list"][0]["provider_name"] == "my-custom-provider"

    def test_save_creates_parent_directory(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that save creates parent directory if it doesn't exist."""
        test_config_path = tmp_path / "nested" / "dir" / "config.yaml"
        monkeypatch.setattr(_config_module, "config_path", test_config_path)

        config = Config(main_model="test")

        asyncio.run(config.save())

        assert test_config_path.exists()


# =============================================================================
# load_config Tests
# =============================================================================


class TestLoadConfig:
    """Tests for load_config function."""

    def test_load_config_returns_builtin_when_missing(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that load_config returns builtin config when file doesn't exist."""
        test_config_path = tmp_path / ".klaude" / "klaude-config.yaml"
        monkeypatch.setattr(_config_module, "config_path", test_config_path)

        # Clear lru_cache
        load_config.cache_clear()

        result = load_config()

        # When user config doesn't exist, returns builtin config
        assert result is not None
        assert len(result.provider_list) > 0  # Has builtin providers
        # Config file is NOT auto-created
        assert not test_config_path.exists()

    def test_load_config_returns_builtin_for_empty_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that load_config returns builtin config for empty user config file."""
        test_config_path = tmp_path / ".klaude" / "klaude-config.yaml"
        test_config_path.parent.mkdir(parents=True)
        test_config_path.write_text("")

        monkeypatch.setattr(_config_module, "config_path", test_config_path)
        load_config.cache_clear()

        result = load_config()
        # Returns builtin config when user config is empty
        assert result is not None
        assert len(result.provider_list) > 0

    def test_load_config_returns_builtin_for_all_commented(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that load_config returns builtin config when all lines are commented."""
        test_config_path = tmp_path / ".klaude" / "klaude-config.yaml"
        test_config_path.parent.mkdir(parents=True)
        test_config_path.write_text("# main_model: test\n# provider_list: []")

        monkeypatch.setattr(_config_module, "config_path", test_config_path)
        load_config.cache_clear()

        result = load_config()
        # Returns builtin config when user config is all commented
        assert result is not None
        assert len(result.provider_list) > 0

    def test_load_config_loads_valid_config(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that load_config merges user config with builtin config."""
        test_config_path = tmp_path / ".klaude" / "klaude-config.yaml"
        test_config_path.parent.mkdir(parents=True)

        config_dict = {
            "main_model": "my-model",
            "provider_list": [
                {
                    "provider_name": "my-provider",
                    "protocol": "openai",
                    "api_key": "test-key",
                    "model_list": [
                        {
                            "model_name": "my-model",
                            "model_params": {"model": "gpt-4"},
                        }
                    ],
                }
            ],
        }
        test_config_path.write_text(str(yaml.dump(config_dict) or ""))

        monkeypatch.setattr(_config_module, "config_path", test_config_path)
        load_config.cache_clear()

        result = load_config()

        assert result is not None
        assert result.main_model == "my-model"
        # User provider is merged with builtin providers
        provider_names = [p.provider_name for p in result.provider_list]
        assert "my-provider" in provider_names
        # Builtin providers are also present
        assert "anthropic" in provider_names or "openai" in provider_names

    def test_load_config_raises_on_invalid_config(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that load_config raises ValueError for invalid config."""
        test_config_path = tmp_path / ".klaude" / "klaude-config.yaml"
        test_config_path.parent.mkdir(parents=True)

        # Invalid config with invalid protocol value
        config_dict = {
            "provider_list": [
                {
                    "provider_name": "test",
                    "protocol": "invalid-protocol",  # Invalid protocol
                    "api_key": "test-key",
                }
            ]
        }
        test_config_path.write_text(str(yaml.dump(config_dict) or ""))

        monkeypatch.setattr(_config_module, "config_path", test_config_path)
        load_config.cache_clear()

        with pytest.raises(ValueError, match="Invalid config file"):
            load_config()

    def test_load_config_caches_result(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Ensure config is cached and requires cache_clear to reload."""
        test_config_path = tmp_path / ".klaude" / "klaude-config.yaml"
        test_config_path.parent.mkdir(parents=True)
        monkeypatch.setattr(_config_module, "config_path", test_config_path)
        load_config.cache_clear()

        # First call returns builtin config (no user config)
        first = load_config()
        assert first is not None
        assert first.main_model is None  # Builtin has no main_model

        # Write a valid user config
        config_dict = {
            "main_model": "after-create",
            "provider_list": [
                {
                    "provider_name": "p",
                    "protocol": "openai",
                    "api_key": "k",
                    "model_list": [
                        {
                            "model_name": "after-create",
                            "model_params": {"model": "gpt-4"},
                        }
                    ],
                }
            ],
        }
        test_config_path.write_text(str(yaml.dump(config_dict) or ""))

        # Without cache_clear, we still get cached result
        cached = load_config()
        assert cached.main_model is None

        # After cache_clear, we get new config
        load_config.cache_clear()
        refreshed = load_config()
        assert refreshed is not None
        assert refreshed.main_model == "after-create"


# =============================================================================
# mask_api_key Tests
# =============================================================================


class TestMaskApiKey:
    """Tests for mask_api_key function."""

    def test_mask_api_key_normal_key(self) -> None:
        """Test masking a normal API key."""
        api_key = "sk-1234567890abcdefghijklmn"
        masked = mask_api_key(api_key)

        assert masked == "sk-123 ... ijklmn"
        assert api_key[:6] in masked
        assert api_key[-6:] in masked

    def test_mask_api_key_short_key(self) -> None:
        """Test that short keys (<= 12 chars) are not masked."""
        short_key = "short123"
        masked = mask_api_key(short_key)

        assert masked == short_key

    def test_mask_api_key_exactly_12_chars(self) -> None:
        """Test that exactly 12 char key is not masked."""
        key_12 = "123456789012"
        masked = mask_api_key(key_12)

        assert masked == key_12

    def test_mask_api_key_13_chars(self) -> None:
        """Test that 13 char key is masked."""
        key_13 = "1234567890123"
        masked = mask_api_key(key_13)

        assert masked == "123456 ... 890123"

    def test_mask_api_key_none(self) -> None:
        """Test masking None returns N/A."""
        masked = mask_api_key(None)
        assert masked == "N/A"

    def test_mask_api_key_na(self) -> None:
        """Test masking 'N/A' returns N/A."""
        masked = mask_api_key("N/A")
        assert masked == "N/A"

    def test_mask_api_key_empty_string(self) -> None:
        """Test masking empty string returns N/A."""
        masked = mask_api_key("")
        assert masked == "N/A"


# =============================================================================
# LLMConfigParameter Integration Tests
# =============================================================================


class TestLLMConfigParameterIntegration:
    """Integration tests for LLMConfigParameter construction from Config."""

    def test_full_config_to_llm_parameter(self) -> None:
        """Test constructing full LLMConfigParameter from Config."""
        provider = llm_param.LLMConfigProviderParameter(
            provider_name="my-provider",
            protocol=llm_param.LLMClientProtocol.RESPONSES,
            base_url="https://api.example.com/v1",
            api_key="test-api-key",
            is_azure=False,
        )
        thinking = llm_param.Thinking(
            reasoning_effort="high",
            reasoning_summary="auto",
            type="enabled",
            budget_tokens=10000,
        )
        model = ModelConfig(
            model_name="advanced-model",
            model_params=llm_param.LLMConfigModelParameter(
                model="gpt-5.1-2025",
                temperature=0.7,
                max_tokens=32000,
                context_limit=368000,
                verbosity="medium",
                thinking=thinking,
            ),
        )
        provider_config = ProviderConfig(**provider.model_dump(), model_list=[model])
        config = Config(
            provider_list=[provider_config],
            main_model="advanced-model",
        )

        llm_config = config.get_model_config("advanced-model")

        # Provider fields
        assert llm_config.provider_name == "my-provider"
        assert llm_config.protocol == llm_param.LLMClientProtocol.RESPONSES
        assert llm_config.base_url == "https://api.example.com/v1"
        assert llm_config.api_key == "test-api-key"
        assert llm_config.is_azure is False

        # Model fields
        assert llm_config.model == "gpt-5.1-2025"
        assert llm_config.temperature == 0.7
        assert llm_config.max_tokens == 32000
        assert llm_config.context_limit == 368000
        assert llm_config.verbosity == "medium"

        # Thinking fields
        assert llm_config.thinking is not None
        assert llm_config.thinking.reasoning_effort == "high"
        assert llm_config.thinking.reasoning_summary == "auto"
        assert llm_config.thinking.type == "enabled"
        assert llm_config.thinking.budget_tokens == 10000

    def test_config_with_openrouter_routing(self) -> None:
        """Test config with OpenRouter provider routing."""
        provider = llm_param.LLMConfigProviderParameter(
            provider_name="openrouter",
            protocol=llm_param.LLMClientProtocol.OPENROUTER,
            api_key="or-key",
        )
        routing = llm_param.OpenRouterProviderRouting(
            sort="throughput",
            allow_fallbacks=True,
        )
        model = ModelConfig(
            model_name="haiku",
            model_params=llm_param.LLMConfigModelParameter(
                model="anthropic/claude-haiku-4.5",
                provider_routing=routing,
            ),
        )
        provider_config = ProviderConfig(**provider.model_dump(), model_list=[model])
        config = Config(
            provider_list=[provider_config],
            main_model="haiku",
        )

        llm_config = config.get_model_config("haiku")

        assert llm_config.provider_routing is not None
        assert llm_config.provider_routing.sort == "throughput"
        assert llm_config.provider_routing.allow_fallbacks is True


class TestSelectModelFromConfig:
    def test_select_model_supports_case_insensitive_exact_match(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import klaude_code.config.select_model as select_model_module
        from klaude_code.config.select_model import select_model_from_config

        provider = llm_param.LLMConfigProviderParameter(
            provider_name="p",
            protocol=llm_param.LLMClientProtocol.OPENAI,
            api_key="test-api-key",
        )
        model = ModelConfig(
            model_name="gpt-5.2",
            model_params=llm_param.LLMConfigModelParameter(model="gpt-5.2-2025-12-01"),
        )
        provider_config = ProviderConfig(**provider.model_dump(), model_list=[model])
        config = Config(provider_list=[provider_config], main_model="gpt-5.2")

        monkeypatch.setattr(select_model_module, "load_config", lambda: config)

        assert select_model_from_config(preferred="GPT-5.2") == "gpt-5.2"

    def test_select_model_supports_normalized_alias_against_model_name(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import klaude_code.config.select_model as select_model_module
        from klaude_code.config.select_model import select_model_from_config

        provider = llm_param.LLMConfigProviderParameter(
            provider_name="p",
            protocol=llm_param.LLMClientProtocol.OPENAI,
            api_key="test-api-key",
        )
        model = ModelConfig(
            model_name="gpt-5.2",
            model_params=llm_param.LLMConfigModelParameter(model="gpt-5.2-2025-12-01"),
        )
        provider_config = ProviderConfig(**provider.model_dump(), model_list=[model])
        config = Config(provider_list=[provider_config], main_model="gpt-5.2")

        monkeypatch.setattr(select_model_module, "load_config", lambda: config)

        assert select_model_from_config(preferred="gpt52") == "gpt-5.2"

    def test_select_model_supports_normalized_punctuation_variants(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import klaude_code.config.select_model as select_model_module
        from klaude_code.config.select_model import select_model_from_config

        provider = llm_param.LLMConfigProviderParameter(
            provider_name="p",
            protocol=llm_param.LLMClientProtocol.OPENAI,
            api_key="test-api-key",
        )
        model = ModelConfig(
            model_name="gpt-5.2",
            model_params=llm_param.LLMConfigModelParameter(model="gpt-5.2-2025-12-01"),
        )
        provider_config = ProviderConfig(**provider.model_dump(), model_list=[model])
        config = Config(provider_list=[provider_config], main_model="gpt-5.2")

        monkeypatch.setattr(select_model_module, "load_config", lambda: config)

        assert select_model_from_config(preferred="gpt_5_2") == "gpt-5.2"

    def test_select_model_supports_normalized_alias_against_model_id(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import klaude_code.config.select_model as select_model_module
        from klaude_code.config.select_model import select_model_from_config

        provider = llm_param.LLMConfigProviderParameter(
            provider_name="p",
            protocol=llm_param.LLMClientProtocol.OPENAI,
            api_key="test-api-key",
        )
        model = ModelConfig(
            model_name="primary",
            model_params=llm_param.LLMConfigModelParameter(model="gpt-5.2-2025-12-01"),
        )
        provider_config = ProviderConfig(**provider.model_dump(), model_list=[model])
        config = Config(provider_list=[provider_config], main_model="primary")

        monkeypatch.setattr(select_model_module, "load_config", lambda: config)

        assert select_model_from_config(preferred="gpt52") == "primary"

    def test_select_model_supports_normalized_alias_with_prefix(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import klaude_code.config.select_model as select_model_module
        from klaude_code.config.select_model import select_model_from_config

        provider = llm_param.LLMConfigProviderParameter(
            provider_name="p",
            protocol=llm_param.LLMClientProtocol.OPENAI,
            api_key="test-api-key",
        )
        model = ModelConfig(
            model_name="primary",
            model_params=llm_param.LLMConfigModelParameter(model="openai/gpt-5.2-2025-12-01"),
        )
        provider_config = ProviderConfig(**provider.model_dump(), model_list=[model])
        config = Config(provider_list=[provider_config], main_model="primary")

        monkeypatch.setattr(select_model_module, "load_config", lambda: config)

        assert select_model_from_config(preferred="openai/gpt52") == "primary"

    def test_select_model_uses_interactive_selector_on_ambiguity(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import types

        import klaude_code.config.select_model as select_model_module
        from klaude_code.config.select_model import select_model_from_config

        provider = llm_param.LLMConfigProviderParameter(
            provider_name="p",
            protocol=llm_param.LLMClientProtocol.OPENAI,
            api_key="test-api-key",
        )
        model_a = ModelConfig(
            model_name="gpt-5.2-2025-12-01",
            model_params=llm_param.LLMConfigModelParameter(model="gpt-5.2-2025-12-01"),
        )
        model_b = ModelConfig(
            model_name="gpt-5.2-2025-12-02",
            model_params=llm_param.LLMConfigModelParameter(model="gpt-5.2-2025-12-02"),
        )
        provider_config = ProviderConfig(**provider.model_dump(), model_list=[model_a, model_b])
        config = Config(provider_list=[provider_config], main_model=model_a.model_name)

        monkeypatch.setattr(select_model_module, "load_config", lambda: config)

        # This test exercises the interactive branch; simulate a TTY.
        monkeypatch.setattr(select_model_module.sys.stdin, "isatty", lambda: True)
        monkeypatch.setattr(select_model_module.sys.stdout, "isatty", lambda: True)

        captured: dict[str, Any] = {}
        questionary_stub: Any = types.ModuleType("questionary")

        class Choice:
            def __init__(self, title: str, value: str) -> None:
                self.title = title
                self.value = value

        class Style:
            def __init__(self, _styles: object) -> None:
                self._styles = _styles

        def select(*, message: str, choices: list[Choice], **kwargs: object) -> object:
            captured["message"] = message
            captured["choices"] = choices
            captured["kwargs"] = kwargs

            class _Result:
                def ask(self) -> str:
                    return model_b.model_name

            return _Result()

        questionary_stub.Choice = Choice
        questionary_stub.Style = Style
        questionary_stub.select = select

        monkeypatch.setitem(sys.modules, "questionary", questionary_stub)

        assert select_model_from_config(preferred="gpt52") == model_b.model_name
        assert captured["message"] == "Select a model (filtered by 'gpt52'):"
        assert len(captured["choices"]) == 2


# =============================================================================
# config_path Tests
# =============================================================================


class TestConfigPath:
    """Tests for config_path constant."""

    def test_config_path_is_in_home_directory(self) -> None:
        """Test that config_path is in home directory."""
        assert config_path.parent.name == ".klaude"
        assert config_path.parent.parent == Path.home()

    def test_config_path_filename(self) -> None:
        """Test that config_path has correct filename."""
        assert config_path.name == "klaude-config.yaml"


# =============================================================================
# Out-of-Box Experience Tests
# =============================================================================


class TestOutOfBoxExperience:
    """Tests simulating various out-of-box configuration scenarios."""

    def test_first_run_no_config_no_api_keys(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """First run: no config file, no API keys set - should return builtin config with limited available models."""
        test_config_path = tmp_path / ".klaude" / "klaude-config.yaml"
        monkeypatch.setattr(_config_module, "config_path", test_config_path)

        # Clear all API key environment variables (including additional providers)
        for env_var in [
            "ANTHROPIC_API_KEY",
            "OPENAI_API_KEY",
            "OPENROUTER_API_KEY",
            "DEEPSEEK_API_KEY",
            "MOONSHOT_API_KEY",
        ]:
            monkeypatch.delenv(env_var, raising=False)

        load_config.cache_clear()
        config = load_config()

        # Config is loaded (builtin)
        assert config is not None
        assert len(config.provider_list) > 0

        # All models exist but most are unavailable (some providers like codex may not need API key)
        all_models = config.iter_model_entries(only_available=False)
        assert len(all_models) > 0

        # Config file is NOT auto-created
        assert not test_config_path.exists()

    def test_first_run_no_config_with_anthropic_key(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """First run: no config file, only ANTHROPIC_API_KEY set - should have anthropic models available."""
        test_config_path = tmp_path / ".klaude" / "klaude-config.yaml"
        monkeypatch.setattr(_config_module, "config_path", test_config_path)

        # Set only Anthropic API key, clear others
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-key-12345")
        for env in ["OPENAI_API_KEY", "OPENROUTER_API_KEY", "DEEPSEEK_API_KEY", "MOONSHOT_API_KEY"]:
            monkeypatch.delenv(env, raising=False)

        load_config.cache_clear()
        config = load_config()

        available_models = config.iter_model_entries(only_available=True)
        available_providers = {m.provider for m in available_models}

        # Anthropic provider should have available models
        assert "anthropic" in available_providers
        # OpenAI provider should NOT have available models (no API key)
        assert "openai" not in available_providers

    def test_first_run_no_config_with_openai_key(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """First run: no config file, only OPENAI_API_KEY set - should have openai models available."""
        test_config_path = tmp_path / ".klaude" / "klaude-config.yaml"
        monkeypatch.setattr(_config_module, "config_path", test_config_path)

        # Set only OpenAI API key, clear others
        monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-test-key-12345")
        for env in ["ANTHROPIC_API_KEY", "OPENROUTER_API_KEY", "DEEPSEEK_API_KEY", "MOONSHOT_API_KEY"]:
            monkeypatch.delenv(env, raising=False)

        load_config.cache_clear()
        config = load_config()

        available_models = config.iter_model_entries(only_available=True)
        available_providers = {m.provider for m in available_models}

        # OpenAI provider should have available models
        assert "openai" in available_providers
        # Anthropic provider should NOT have available models (no API key)
        assert "anthropic" not in available_providers

    def test_first_run_no_config_with_multiple_keys(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """First run: no config file, multiple API keys set - should have all corresponding models available."""
        test_config_path = tmp_path / ".klaude" / "klaude-config.yaml"
        monkeypatch.setattr(_config_module, "config_path", test_config_path)

        # Set multiple API keys
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-test")
        for env in ["OPENROUTER_API_KEY", "DEEPSEEK_API_KEY", "MOONSHOT_API_KEY"]:
            monkeypatch.delenv(env, raising=False)

        load_config.cache_clear()
        config = load_config()

        available_models = config.iter_model_entries(only_available=True)
        available_providers = {m.provider for m in available_models}

        # Both anthropic and openai providers should have available models
        assert "anthropic" in available_providers
        assert "openai" in available_providers
        # OpenRouter should NOT have available models
        assert "openrouter" not in available_providers

    def test_empty_config_file_uses_builtin(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Empty config file should fall back to builtin config."""
        test_config_path = tmp_path / ".klaude" / "klaude-config.yaml"
        test_config_path.parent.mkdir(parents=True)
        test_config_path.write_text("")

        monkeypatch.setattr(_config_module, "config_path", test_config_path)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        for env in ["OPENAI_API_KEY", "OPENROUTER_API_KEY", "DEEPSEEK_API_KEY", "MOONSHOT_API_KEY"]:
            monkeypatch.delenv(env, raising=False)

        load_config.cache_clear()
        config = load_config()

        # Should still have builtin providers
        provider_names = [p.provider_name for p in config.provider_list]
        assert "anthropic" in provider_names

        # Anthropic models should be available
        available = config.iter_model_entries(only_available=True)
        assert any(m.provider == "anthropic" for m in available)

    def test_user_config_merges_builtin_provider_models(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """User config with same provider name should merge model_list with builtin."""
        test_config_path = tmp_path / ".klaude" / "klaude-config.yaml"
        test_config_path.parent.mkdir(parents=True)

        # User adds a custom model to existing "anthropic" provider
        user_config = {
            "provider_list": [
                {
                    "provider_name": "anthropic",
                    "model_list": [
                        {
                            "model_name": "my-custom-claude",
                            "model_params": {"model": "claude-custom-model"},
                        }
                    ],
                }
            ]
        }
        test_config_path.write_text(str(yaml.dump(user_config) or ""))

        monkeypatch.setattr(_config_module, "config_path", test_config_path)
        load_config.cache_clear()
        config = load_config()

        # Find the anthropic provider
        anthropic_provider = next((p for p in config.provider_list if p.provider_name == "anthropic"), None)
        assert anthropic_provider is not None

        # Should have BOTH user's custom model AND builtin models
        model_names = [m.model_name for m in anthropic_provider.model_list]
        assert "my-custom-claude" in model_names
        assert "sonnet" in model_names
        assert "opus" in model_names

    def test_user_config_overrides_builtin_model(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """User config with same model name should override builtin model."""
        test_config_path = tmp_path / ".klaude" / "klaude-config.yaml"
        test_config_path.parent.mkdir(parents=True)

        # User overrides the builtin "sonnet" model
        user_config = {
            "provider_list": [
                {
                    "provider_name": "anthropic",
                    "model_list": [
                        {
                            "model_name": "sonnet",
                            "model_params": {"model": "my-custom-sonnet-model", "max_tokens": 99999},
                        }
                    ],
                }
            ]
        }
        test_config_path.write_text(str(yaml.dump(user_config) or ""))

        monkeypatch.setattr(_config_module, "config_path", test_config_path)
        load_config.cache_clear()
        config = load_config()

        # Find the anthropic provider
        anthropic_provider = next((p for p in config.provider_list if p.provider_name == "anthropic"), None)
        assert anthropic_provider is not None

        # Find the sonnet model
        sonnet_model = next((m for m in anthropic_provider.model_list if m.model_name == "sonnet"), None)
        assert sonnet_model is not None

        # Should use user's custom model params
        assert sonnet_model.model_params.model == "my-custom-sonnet-model"
        assert sonnet_model.model_params.max_tokens == 99999

    def test_user_provider_settings_override_builtin(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """User's provider-level settings should override builtin."""
        test_config_path = tmp_path / ".klaude" / "klaude-config.yaml"
        test_config_path.parent.mkdir(parents=True)

        # User overrides api_key for anthropic provider
        user_config = {
            "provider_list": [
                {
                    "provider_name": "anthropic",
                    "api_key": "sk-user-custom-key",
                }
            ]
        }
        test_config_path.write_text(str(yaml.dump(user_config) or ""))

        monkeypatch.setattr(_config_module, "config_path", test_config_path)
        load_config.cache_clear()
        config = load_config()

        # Find the anthropic provider
        anthropic_provider = next((p for p in config.provider_list if p.provider_name == "anthropic"), None)
        assert anthropic_provider is not None

        # Should use user's api_key
        assert anthropic_provider.api_key == "sk-user-custom-key"

        # But should still have builtin models
        model_names = [m.model_name for m in anthropic_provider.model_list]
        assert "sonnet" in model_names
        assert "opus" in model_names

    def test_user_config_adds_new_provider(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """User config with new provider should be added to builtin providers."""
        test_config_path = tmp_path / ".klaude" / "klaude-config.yaml"
        test_config_path.parent.mkdir(parents=True)

        # User adds a new provider
        user_config = {
            "provider_list": [
                {
                    "provider_name": "my-custom-provider",
                    "protocol": "openai",
                    "api_key": "sk-custom-key",
                    "base_url": "https://my-api.example.com/v1",
                    "model_list": [
                        {
                            "model_name": "custom-model",
                            "model_params": {"model": "custom-model-id"},
                        }
                    ],
                }
            ]
        }
        test_config_path.write_text(str(yaml.dump(user_config) or ""))

        monkeypatch.setattr(_config_module, "config_path", test_config_path)
        load_config.cache_clear()
        config = load_config()

        provider_names = [p.provider_name for p in config.provider_list]

        # Should have both user's provider and builtin providers
        assert "my-custom-provider" in provider_names
        assert "anthropic" in provider_names
        assert "openai" in provider_names

    def test_user_main_model_takes_precedence(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """User's main_model setting should take precedence over builtin."""
        test_config_path = tmp_path / ".klaude" / "klaude-config.yaml"
        test_config_path.parent.mkdir(parents=True)

        user_config = {"main_model": "my-favorite-model"}
        test_config_path.write_text(str(yaml.dump(user_config) or ""))

        monkeypatch.setattr(_config_module, "config_path", test_config_path)
        load_config.cache_clear()
        config = load_config()

        assert config.main_model == "my-favorite-model"

    def test_builtin_config_has_no_main_model(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Builtin config should NOT have main_model set (user must choose)."""
        test_config_path = tmp_path / ".klaude" / "klaude-config.yaml"
        monkeypatch.setattr(_config_module, "config_path", test_config_path)

        load_config.cache_clear()
        config = load_config()

        # Builtin should not preset main_model
        assert config.main_model is None

    def test_deepseek_provider_available(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """DeepSeek provider should be available when DEEPSEEK_API_KEY is set."""
        test_config_path = tmp_path / ".klaude" / "klaude-config.yaml"
        monkeypatch.setattr(_config_module, "config_path", test_config_path)

        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-deepseek-test")
        for env in ["ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY", "MOONSHOT_API_KEY"]:
            monkeypatch.delenv(env, raising=False)

        load_config.cache_clear()
        config = load_config()

        available = config.iter_model_entries(only_available=True)
        available_providers = {m.provider for m in available}

        assert "deepseek" in available_providers
        # Others should not be available
        assert "anthropic" not in available_providers
        assert "openai" not in available_providers

    def test_openrouter_provider_available(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """OpenRouter provider should be available when OPENROUTER_API_KEY is set."""
        test_config_path = tmp_path / ".klaude" / "klaude-config.yaml"
        monkeypatch.setattr(_config_module, "config_path", test_config_path)

        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
        for env in ["ANTHROPIC_API_KEY", "OPENAI_API_KEY", "DEEPSEEK_API_KEY", "MOONSHOT_API_KEY"]:
            monkeypatch.delenv(env, raising=False)

        load_config.cache_clear()
        config = load_config()

        available = config.iter_model_entries(only_available=True)
        available_providers = {m.provider for m in available}

        assert "openrouter" in available_providers
        # Others should not be available
        assert "anthropic" not in available_providers

    def test_all_providers_available(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Multiple providers should be available when their API keys are set."""
        test_config_path = tmp_path / ".klaude" / "klaude-config.yaml"
        monkeypatch.setattr(_config_module, "config_path", test_config_path)

        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-test")
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-deepseek-test")

        load_config.cache_clear()
        config = load_config()

        available = config.iter_model_entries(only_available=True)
        available_providers = {m.provider for m in available}

        # All major providers should be available
        assert "anthropic" in available_providers
        assert "openai" in available_providers
        assert "openrouter" in available_providers
        assert "deepseek" in available_providers

    def test_user_sub_agent_models_merged(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """User's sub_agent_models should be merged with builtin."""
        test_config_path = tmp_path / ".klaude" / "klaude-config.yaml"
        test_config_path.parent.mkdir(parents=True)

        user_config = {"sub_agent_models": {"explore": "my-fast-model", "oracle": "my-smart-model"}}
        test_config_path.write_text(str(yaml.dump(user_config) or ""))

        monkeypatch.setattr(_config_module, "config_path", test_config_path)
        load_config.cache_clear()
        config = load_config()

        # Keys are normalized to canonical form (Explore, Oracle)
        assert config.sub_agent_models.get("Explore") == "my-fast-model"
        assert config.sub_agent_models.get("Oracle") == "my-smart-model"

    def test_commented_config_uses_builtin(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Fully commented config should use builtin config."""
        test_config_path = tmp_path / ".klaude" / "klaude-config.yaml"
        test_config_path.parent.mkdir(parents=True)

        commented_content = """# This is a comment
# main_model: some-model
# provider_list:
#   - provider_name: test
"""
        test_config_path.write_text(commented_content)

        monkeypatch.setattr(_config_module, "config_path", test_config_path)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")

        load_config.cache_clear()
        config = load_config()

        # Should still have builtin providers
        provider_names = [p.provider_name for p in config.provider_list]
        assert "anthropic" in provider_names

        # Anthropic models should be available
        available = config.iter_model_entries(only_available=True)
        assert any(m.model_name == "sonnet" for m in available)
