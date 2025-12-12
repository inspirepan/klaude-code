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
ModelConfig = _config_module.ModelConfig
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
            provider="openai",
            model_params=model_params,
        )

        assert config.model_name == "test-model"
        assert config.provider == "openai"
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
            provider="openai",
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
    def sample_provider(self) -> llm_param.LLMConfigProviderParameter:
        """Create a sample provider for testing."""
        return llm_param.LLMConfigProviderParameter(
            provider_name="test-provider",
            protocol=llm_param.LLMClientProtocol.OPENAI,
            api_key="test-api-key",
            base_url="https://api.example.com/v1",
        )

    @pytest.fixture
    def sample_model_config(self) -> ModelConfig:
        """Create a sample model config for testing."""
        return ModelConfig(
            model_name="test-model",
            provider="test-provider",
            model_params=llm_param.LLMConfigModelParameter(
                model="test-model-v1",
                max_tokens=4096,
            ),
        )

    @pytest.fixture
    def sample_config(
        self, sample_provider: llm_param.LLMConfigProviderParameter, sample_model_config: ModelConfig
    ) -> Config:
        """Create a sample Config for testing."""
        return Config(
            provider_list=[sample_provider],
            model_list=[sample_model_config],
            main_model="test-model",
        )

    def test_config_creation(self, sample_config: Config) -> None:
        """Test basic Config creation."""
        assert sample_config.main_model == "test-model"
        assert len(sample_config.provider_list) == 1
        assert len(sample_config.model_list) == 1
        assert sample_config.sub_agent_models == {}
        assert sample_config.theme is None

    def test_config_with_theme(
        self, sample_provider: llm_param.LLMConfigProviderParameter, sample_model_config: ModelConfig
    ) -> None:
        """Test Config with theme."""
        config = Config(
            provider_list=[sample_provider],
            model_list=[sample_model_config],
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

    def test_get_main_model_config(self, sample_config: Config) -> None:
        """Test getting main model config."""
        llm_config = sample_config.get_main_model_config()

        assert llm_config.model == "test-model-v1"
        assert llm_config.provider_name == "test-provider"

    def test_get_model_config_unknown_model(self, sample_config: Config) -> None:
        """Test getting config for unknown model raises error."""
        with pytest.raises(ValueError, match="Unknown model: nonexistent-model"):
            sample_config.get_model_config("nonexistent-model")

    def test_get_model_config_unknown_provider(self, sample_provider: llm_param.LLMConfigProviderParameter) -> None:
        """Test getting config for model with unknown provider raises error."""
        model = ModelConfig(
            model_name="orphan-model",
            provider="nonexistent-provider",
            model_params=llm_param.LLMConfigModelParameter(model="some-model"),
        )
        config = Config(
            provider_list=[sample_provider],
            model_list=[model],
            main_model="orphan-model",
        )

        with pytest.raises(ValueError, match="Unknown provider: nonexistent-provider"):
            config.get_model_config("orphan-model")

    def test_sub_agent_models_normalization(
        self, sample_provider: llm_param.LLMConfigProviderParameter, sample_model_config: ModelConfig
    ) -> None:
        """Test that sub_agent_models keys are normalized to canonical names."""
        # Use lowercase keys that should be normalized
        config = Config(
            provider_list=[sample_provider],
            model_list=[sample_model_config],
            main_model="test-model",
            sub_agent_models={"task": "model-a", "oracle": "model-b"},
        )

        # Keys should be normalized to canonical form (matching SubAgentProfile names)
        # Based on sub_agent.py, the canonical names are "Task", "Oracle", etc.
        assert "Task" in config.sub_agent_models
        assert "Oracle" in config.sub_agent_models
        assert config.sub_agent_models["Task"] == "model-a"
        assert config.sub_agent_models["Oracle"] == "model-b"

    def test_sub_agent_models_empty(
        self, sample_provider: llm_param.LLMConfigProviderParameter, sample_model_config: ModelConfig
    ) -> None:
        """Test that empty sub_agent_models is handled correctly."""
        config = Config(
            provider_list=[sample_provider],
            model_list=[sample_model_config],
            main_model="test-model",
            sub_agent_models={},
        )
        assert config.sub_agent_models == {}

    def test_sub_agent_models_none(
        self, sample_provider: llm_param.LLMConfigProviderParameter, sample_model_config: ModelConfig
    ) -> None:
        """Test that None sub_agent_models is handled correctly."""
        # Pass data through model_validate to trigger validator
        data: dict[str, Any] = {
            "provider_list": [sample_provider.model_dump()],
            "model_list": [sample_model_config.model_dump()],
            "main_model": "test-model",
            "sub_agent_models": None,
        }
        config = Config.model_validate(data)
        assert config.sub_agent_models == {}


class TestConfigSave:
    """Tests for Config.save() method."""

    def test_save_config(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test saving config to file."""
        test_config_path = tmp_path / "test-config.yaml"
        monkeypatch.setattr(_config_module, "config_path", test_config_path)

        provider = llm_param.LLMConfigProviderParameter(
            provider_name="test-provider",
            protocol=llm_param.LLMClientProtocol.OPENAI,
            api_key="test-key",
        )
        model = ModelConfig(
            model_name="test-model",
            provider="test-provider",
            model_params=llm_param.LLMConfigModelParameter(model="gpt-4"),
        )
        config = Config(
            provider_list=[provider],
            model_list=[model],
            main_model="test-model",
        )

        asyncio.run(config.save())

        assert test_config_path.exists()
        saved_content = yaml.safe_load(test_config_path.read_text())
        assert saved_content["main_model"] == "test-model"
        assert len(saved_content["provider_list"]) == 1
        assert len(saved_content["model_list"]) == 1

    def test_save_creates_parent_directory(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that save creates parent directory if it doesn't exist."""
        test_config_path = tmp_path / "nested" / "dir" / "config.yaml"
        monkeypatch.setattr(_config_module, "config_path", test_config_path)

        provider = llm_param.LLMConfigProviderParameter(
            provider_name="test",
            protocol=llm_param.LLMClientProtocol.OPENAI,
        )
        model = ModelConfig(
            model_name="test",
            provider="test",
            model_params=llm_param.LLMConfigModelParameter(),
        )
        config = Config(
            provider_list=[provider],
            model_list=[model],
            main_model="test",
        )

        asyncio.run(config.save())

        assert test_config_path.exists()


# =============================================================================
# load_config Tests
# =============================================================================


class TestLoadConfig:
    """Tests for load_config function."""

    def test_load_config_creates_example_when_missing(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that load_config creates example config when file doesn't exist."""
        test_config_path = tmp_path / ".klaude" / "klaude-config.yaml"
        monkeypatch.setattr(_config_module, "config_path", test_config_path)

        # Clear lru_cache
        load_config.cache_clear()

        result = load_config()

        # When config doesn't exist, it returns None and creates commented example
        assert result is None
        assert test_config_path.exists()

        # Verify the file contains commented lines
        content = test_config_path.read_text()
        assert content.startswith("#")

    def test_load_config_returns_none_for_empty_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that load_config returns None for empty config file."""
        test_config_path = tmp_path / ".klaude" / "klaude-config.yaml"
        test_config_path.parent.mkdir(parents=True)
        test_config_path.write_text("")

        monkeypatch.setattr(_config_module, "config_path", test_config_path)
        load_config.cache_clear()

        result = load_config()
        assert result is None

    def test_load_config_returns_none_for_all_commented(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that load_config returns None when all lines are commented."""
        test_config_path = tmp_path / ".klaude" / "klaude-config.yaml"
        test_config_path.parent.mkdir(parents=True)
        test_config_path.write_text("# main_model: test\n# provider_list: []")

        monkeypatch.setattr(_config_module, "config_path", test_config_path)
        load_config.cache_clear()

        result = load_config()
        assert result is None

    def test_load_config_loads_valid_config(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that load_config loads a valid config file."""
        test_config_path = tmp_path / ".klaude" / "klaude-config.yaml"
        test_config_path.parent.mkdir(parents=True)

        config_dict = {
            "main_model": "my-model",
            "provider_list": [
                {
                    "provider_name": "my-provider",
                    "protocol": "openai",
                    "api_key": "test-key",
                }
            ],
            "model_list": [
                {
                    "model_name": "my-model",
                    "provider": "my-provider",
                    "model_params": {"model": "gpt-4"},
                }
            ],
        }
        test_config_path.write_text(str(yaml.dump(config_dict) or ""))

        monkeypatch.setattr(_config_module, "config_path", test_config_path)
        load_config.cache_clear()

        result = load_config()

        assert result is not None
        assert result.main_model == "my-model"
        assert len(result.provider_list) == 1
        assert result.provider_list[0].provider_name == "my-provider"

    def test_load_config_raises_on_invalid_config(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that load_config raises ValueError for invalid config."""
        test_config_path = tmp_path / ".klaude" / "klaude-config.yaml"
        test_config_path.parent.mkdir(parents=True)

        # Invalid config missing required fields
        config_dict = {"main_model": "test"}
        test_config_path.write_text(str(yaml.dump(config_dict) or ""))

        monkeypatch.setattr(_config_module, "config_path", test_config_path)
        load_config.cache_clear()

        with pytest.raises(ValueError, match="Invalid config file"):
            load_config()

    def test_load_config_does_not_cache_missing_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Ensure a missing config (returning None) does not get cached."""
        test_config_path = tmp_path / ".klaude" / "klaude-config.yaml"
        monkeypatch.setattr(_config_module, "config_path", test_config_path)
        load_config.cache_clear()

        # First call should create commented example and return None
        first = load_config()
        assert first is None

        # Write a valid config and ensure it loads without needing cache_clear
        config_dict = {
            "main_model": "after-create",
            "provider_list": [
                {
                    "provider_name": "p",
                    "protocol": "openai",
                    "api_key": "k",
                }
            ],
            "model_list": [
                {
                    "model_name": "after-create",
                    "provider": "p",
                    "model_params": {"model": "gpt-4"},
                }
            ],
        }
        test_config_path.write_text(str(yaml.dump(config_dict) or ""))

        second = load_config()
        assert second is not None
        assert second.main_model == "after-create"


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
            provider="my-provider",
            model_params=llm_param.LLMConfigModelParameter(
                model="gpt-5.1-2025",
                temperature=0.7,
                max_tokens=32000,
                context_limit=368000,
                verbosity="medium",
                thinking=thinking,
            ),
        )
        config = Config(
            provider_list=[provider],
            model_list=[model],
            main_model="advanced-model",
        )

        llm_config = config.get_main_model_config()

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
            provider="openrouter",
            model_params=llm_param.LLMConfigModelParameter(
                model="anthropic/claude-haiku-4.5",
                provider_routing=routing,
            ),
        )
        config = Config(
            provider_list=[provider],
            model_list=[model],
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
        )
        model = ModelConfig(
            model_name="gpt-5.2",
            provider="p",
            model_params=llm_param.LLMConfigModelParameter(model="gpt-5.2-2025-12-01"),
        )
        config = Config(provider_list=[provider], model_list=[model], main_model="gpt-5.2")

        monkeypatch.setattr(select_model_module, "load_config", lambda: config)

        assert select_model_from_config(preferred="GPT-5.2") == "gpt-5.2"

    def test_select_model_supports_normalized_alias_against_model_name(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import klaude_code.config.select_model as select_model_module
        from klaude_code.config.select_model import select_model_from_config

        provider = llm_param.LLMConfigProviderParameter(
            provider_name="p",
            protocol=llm_param.LLMClientProtocol.OPENAI,
        )
        model = ModelConfig(
            model_name="gpt-5.2",
            provider="p",
            model_params=llm_param.LLMConfigModelParameter(model="gpt-5.2-2025-12-01"),
        )
        config = Config(provider_list=[provider], model_list=[model], main_model="gpt-5.2")

        monkeypatch.setattr(select_model_module, "load_config", lambda: config)

        assert select_model_from_config(preferred="gpt52") == "gpt-5.2"

    def test_select_model_supports_normalized_punctuation_variants(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import klaude_code.config.select_model as select_model_module
        from klaude_code.config.select_model import select_model_from_config

        provider = llm_param.LLMConfigProviderParameter(
            provider_name="p",
            protocol=llm_param.LLMClientProtocol.OPENAI,
        )
        model = ModelConfig(
            model_name="gpt-5.2",
            provider="p",
            model_params=llm_param.LLMConfigModelParameter(model="gpt-5.2-2025-12-01"),
        )
        config = Config(provider_list=[provider], model_list=[model], main_model="gpt-5.2")

        monkeypatch.setattr(select_model_module, "load_config", lambda: config)

        assert select_model_from_config(preferred="gpt_5_2") == "gpt-5.2"

    def test_select_model_supports_normalized_alias_against_model_id(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import klaude_code.config.select_model as select_model_module
        from klaude_code.config.select_model import select_model_from_config

        provider = llm_param.LLMConfigProviderParameter(
            provider_name="p",
            protocol=llm_param.LLMClientProtocol.OPENAI,
        )
        model = ModelConfig(
            model_name="primary",
            provider="p",
            model_params=llm_param.LLMConfigModelParameter(model="gpt-5.2-2025-12-01"),
        )
        config = Config(provider_list=[provider], model_list=[model], main_model="primary")

        monkeypatch.setattr(select_model_module, "load_config", lambda: config)

        assert select_model_from_config(preferred="gpt52") == "primary"

    def test_select_model_supports_normalized_alias_with_prefix(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import klaude_code.config.select_model as select_model_module
        from klaude_code.config.select_model import select_model_from_config

        provider = llm_param.LLMConfigProviderParameter(
            provider_name="p",
            protocol=llm_param.LLMClientProtocol.OPENAI,
        )
        model = ModelConfig(
            model_name="primary",
            provider="p",
            model_params=llm_param.LLMConfigModelParameter(model="openai/gpt-5.2-2025-12-01"),
        )
        config = Config(provider_list=[provider], model_list=[model], main_model="primary")

        monkeypatch.setattr(select_model_module, "load_config", lambda: config)

        assert select_model_from_config(preferred="openai/gpt52") == "primary"

    def test_select_model_uses_interactive_selector_on_ambiguity(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import types

        import klaude_code.config.select_model as select_model_module
        from klaude_code.config.select_model import select_model_from_config

        provider = llm_param.LLMConfigProviderParameter(
            provider_name="p",
            protocol=llm_param.LLMClientProtocol.OPENAI,
        )
        model_a = ModelConfig(
            model_name="gpt-5.2-2025-12-01",
            provider="p",
            model_params=llm_param.LLMConfigModelParameter(model="gpt-5.2-2025-12-01"),
        )
        model_b = ModelConfig(
            model_name="gpt-5.2-2025-12-02",
            provider="p",
            model_params=llm_param.LLMConfigModelParameter(model="gpt-5.2-2025-12-02"),
        )
        config = Config(provider_list=[provider], model_list=[model_a, model_b], main_model=model_a.model_name)

        monkeypatch.setattr(select_model_module, "load_config", lambda: config)

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
