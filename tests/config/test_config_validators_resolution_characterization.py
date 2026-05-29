"""Characterization tests for the config layer (GROUP G2).

These lock in the CURRENT observable behavior of:
  - the duplicated ``_normalize_sub_agent_models`` validator on both
    ``UserConfig`` and ``Config``
  - the duplicated ``_normalize_provider_name_in_model`` validator on both
    ``ProviderConfig`` and ``UserProviderConfig``
  - ``normalize_provider_name`` (casefold-based alias lookup that PRESERVES the
    original casing for non-aliased names)
  - provider/model resolution helpers: ``resolve_model_location``,
    ``resolve_model_location_prefer_available``, ``get_model_config``,
    ``diagnose_model``, including case-insensitive (casefold) provider matching.

They assert what the code DOES today, not what it arguably should do, so a later
refactor (e.g. de-duplicating the validators) can be proven behavior-preserving.

These are pure in-memory unit tests; ``isolated_home`` is depended on defensively
per tests/AGENTS.md since provider credential checks may consult ``Path.home()``.
"""

from pathlib import Path

import pytest

from klaude_code.config.config import (
    Config,
    ModelAvailability,
    ModelConfig,
    ProviderConfig,
    UserConfig,
    UserProviderConfig,
    normalize_provider_name,
)
from klaude_code.protocol import llm_param


def _make_provider(
    *,
    provider_name: str,
    model_names: list[str],
    api_key: str | None = "key",
    disabled: bool = False,
    disabled_models: set[str] | None = None,
    aliases: dict[str, list[str]] | None = None,
) -> ProviderConfig:
    disabled_models = disabled_models or set()
    aliases = aliases or {}
    return ProviderConfig(
        provider_name=provider_name,
        protocol=llm_param.LLMClientProtocol.OPENAI,
        api_key=api_key,
        disabled=disabled,
        model_list=[
            ModelConfig(
                model_name=name,
                model_id=name,
                model_alias=aliases.get(name, []),
                disabled=(name in disabled_models),
            )
            for name in model_names
        ],
    )


# =============================================================================
# normalize_provider_name (casefold alias lookup)
# =============================================================================


class TestNormalizeProviderName:
    def test_copilot_alias_maps_to_github_copilot(self) -> None:
        assert normalize_provider_name("copilot") == "github-copilot"

    def test_copilot_alias_is_casefold_insensitive(self) -> None:
        assert normalize_provider_name("COPILOT") == "github-copilot"
        assert normalize_provider_name("CoPilot") == "github-copilot"

    def test_non_alias_name_is_returned_unchanged_preserving_case(self) -> None:
        # Only aliases are remapped; the original casing is preserved otherwise.
        assert normalize_provider_name("openai") == "openai"
        assert normalize_provider_name("OpenAI") == "OpenAI"
        assert normalize_provider_name("OpenRouter") == "OpenRouter"


# =============================================================================
# _normalize_sub_agent_models (duplicated on UserConfig and Config)
# =============================================================================


class TestNormalizeSubAgentModelsUserConfig:
    def test_preferences_are_stripped_and_empty_dropped(self, isolated_home: Path) -> None:
        del isolated_home
        uc = UserConfig.model_validate(
            {
                "main_model": "  sonnet  ",
                "fast_model": ["  a ", "", "b"],
                "compact_model": None,
            }
        )
        assert uc.main_model == "sonnet"
        # List items are stripped and empties removed, preserving order.
        assert uc.fast_model == ["a", "b"]
        assert uc.compact_model is None

    def test_sub_agent_keys_are_lowercased_to_canonical_profile_names(self, isolated_home: Path) -> None:
        del isolated_home
        uc = UserConfig.model_validate(
            {
                "sub_agent_models": {
                    "FINDER": "opus",
                    "  Code-Reviewer ": ["m1", "m2"],
                },
            }
        )
        # Keys are matched case-insensitively against canonical profile names
        # (finder, code-reviewer, ...) and rewritten to the canonical lowercase form.
        assert uc.sub_agent_models == {"finder": "opus", "code-reviewer": ["m1", "m2"]}

    def test_unknown_sub_agent_keys_are_dropped(self, isolated_home: Path) -> None:
        del isolated_home
        uc = UserConfig.model_validate({"sub_agent_models": {"bogus": "x", "finder": "opus"}})
        assert uc.sub_agent_models == {"finder": "opus"}

    def test_none_sub_agent_values_are_dropped(self, isolated_home: Path) -> None:
        del isolated_home
        uc = UserConfig.model_validate({"sub_agent_models": {"general-purpose": None, "finder": "opus"}})
        assert uc.sub_agent_models == {"finder": "opus"}

    def test_empty_string_sub_agent_value_is_dropped(self, isolated_home: Path) -> None:
        del isolated_home
        uc = UserConfig.model_validate({"sub_agent_models": {"code-simplifier": ""}})
        assert uc.sub_agent_models == {}

    def test_missing_sub_agent_models_defaults_to_empty_dict(self, isolated_home: Path) -> None:
        del isolated_home
        uc = UserConfig.model_validate({})
        assert uc.sub_agent_models == {}


class TestNormalizeSubAgentModelsConfig:
    """Config carries the exact same (duplicated) normalization logic."""

    def test_preferences_and_sub_agent_models_normalized_identically(self, isolated_home: Path) -> None:
        del isolated_home
        cfg = Config.model_validate(
            {
                "main_model": "",
                "fast_model": "  fast ",
                "sub_agent_models": {"Finder": "  haiku ", "CODE-SIMPLIFIER": ""},
            }
        )
        # Empty main_model normalizes to None.
        assert cfg.main_model is None
        assert cfg.fast_model == "fast"
        # Whitespace-stripped value kept; empty value dropped.
        assert cfg.sub_agent_models == {"finder": "haiku"}


# =============================================================================
# _normalize_provider_name_in_model (duplicated on ProviderConfig + UserProviderConfig)
# =============================================================================


class TestNormalizeProviderNameInModel:
    def test_user_provider_config_normalizes_copilot_alias(self, isolated_home: Path) -> None:
        del isolated_home
        upc = UserProviderConfig.model_validate({"provider_name": "Copilot"})
        assert upc.provider_name == "github-copilot"

    def test_provider_config_normalizes_copilot_alias_casefold(self, isolated_home: Path) -> None:
        del isolated_home
        pc = ProviderConfig.model_validate({"provider_name": "COPILOT", "protocol": "openai"})
        assert pc.provider_name == "github-copilot"

    def test_provider_config_preserves_non_alias_name_case(self, isolated_home: Path) -> None:
        del isolated_home
        pc = ProviderConfig.model_validate({"provider_name": "OpenAI", "protocol": "openai"})
        assert pc.provider_name == "OpenAI"

    def test_user_provider_config_preserves_non_alias_name_case(self, isolated_home: Path) -> None:
        del isolated_home
        upc = UserProviderConfig.model_validate({"provider_name": "OpenRouter"})
        assert upc.provider_name == "OpenRouter"


# =============================================================================
# resolve_model_location (no auth/availability checks, casefold provider match)
# =============================================================================


class TestResolveModelLocation:
    @pytest.fixture
    def config(self, isolated_home: Path) -> Config:
        del isolated_home
        return Config(
            provider_list=[
                _make_provider(
                    provider_name="OpenAI",
                    model_names=["gpt-5.4"],
                    aliases={"gpt-5.4": ["gpt"]},
                ),
                _make_provider(provider_name="OpenRouter", model_names=["opus"]),
            ]
        )

    def test_qualified_returns_provider_with_original_casing(self, config: Config) -> None:
        # Provider matching is casefold-insensitive, but the returned provider
        # name preserves the config's original casing ("OpenAI").
        assert config.resolve_model_location("gpt-5.4@openai") == ("gpt-5.4", "OpenAI")
        assert config.resolve_model_location("gpt-5.4@OPENAI") == ("gpt-5.4", "OpenAI")

    def test_unqualified_returns_first_provider_defining_model(self, config: Config) -> None:
        assert config.resolve_model_location("gpt-5.4") == ("gpt-5.4", "OpenAI")
        assert config.resolve_model_location("opus") == ("opus", "OpenRouter")

    def test_alias_resolves_to_canonical_model_name(self, config: Config) -> None:
        assert config.resolve_model_location("gpt@openai") == ("gpt-5.4", "OpenAI")

    def test_missing_model_in_qualified_provider_returns_none(self, config: Config) -> None:
        assert config.resolve_model_location("missing@openai") is None

    def test_unknown_provider_returns_none(self, config: Config) -> None:
        assert config.resolve_model_location("gpt-5.4@unknown") is None

    def test_unknown_unqualified_model_returns_none(self, config: Config) -> None:
        assert config.resolve_model_location("nope") is None


class TestResolveModelLocationPreferAvailable:
    def test_skips_disabled_provider_and_picks_available(self, isolated_home: Path) -> None:
        del isolated_home
        config = Config(
            provider_list=[
                _make_provider(provider_name="OpenAI", model_names=["shared"], disabled=True),
                _make_provider(provider_name="OpenRouter", model_names=["shared"]),
            ]
        )
        assert config.resolve_model_location_prefer_available("shared") == ("shared", "OpenRouter")

    def test_skips_missing_credentials_provider(self, isolated_home: Path) -> None:
        del isolated_home
        config = Config(
            provider_list=[
                _make_provider(provider_name="OpenAI", model_names=["shared"], api_key=None),
                _make_provider(provider_name="OpenRouter", model_names=["shared"]),
            ]
        )
        assert config.resolve_model_location_prefer_available("shared") == ("shared", "OpenRouter")

    def test_returns_none_when_all_unavailable(self, isolated_home: Path) -> None:
        del isolated_home
        config = Config(
            provider_list=[
                _make_provider(provider_name="OpenAI", model_names=["shared"], api_key=None),
            ]
        )
        assert config.resolve_model_location_prefer_available("shared") is None


# =============================================================================
# get_model_config (casefold provider matching + error messages)
# =============================================================================


class TestGetModelConfig:
    @pytest.fixture
    def config(self, isolated_home: Path) -> Config:
        del isolated_home
        return Config(
            provider_list=[
                _make_provider(provider_name="OpenAI", model_names=["gpt-5.4"]),
                _make_provider(provider_name="OpenRouter", model_names=["opus"]),
            ]
        )

    def test_case_insensitive_provider_match_returns_llm_config(self, config: Config) -> None:
        llm_config = config.get_model_config("gpt-5.4@OPENAI")
        assert llm_config.model_id == "gpt-5.4"
        assert llm_config.protocol == llm_param.LLMClientProtocol.OPENAI

    def test_unqualified_resolves_first_matching_provider(self, config: Config) -> None:
        llm_config = config.get_model_config("opus")
        assert llm_config.model_id == "opus"

    def test_unknown_model_raises_value_error(self, config: Config) -> None:
        with pytest.raises(ValueError, match="Unknown model: nope"):
            config.get_model_config("nope")

    def test_qualified_disabled_provider_raises(self, isolated_home: Path) -> None:
        del isolated_home
        config = Config(provider_list=[_make_provider(provider_name="OpenAI", model_names=["gpt-5.4"], disabled=True)])
        with pytest.raises(ValueError, match="disabled"):
            config.get_model_config("gpt-5.4@openai")

    def test_qualified_missing_credentials_raises(self, isolated_home: Path) -> None:
        del isolated_home
        config = Config(provider_list=[_make_provider(provider_name="OpenAI", model_names=["gpt-5.4"], api_key=None)])
        with pytest.raises(ValueError, match="missing credentials"):
            config.get_model_config("gpt-5.4@openai")

    def test_qualified_disabled_model_raises(self, isolated_home: Path) -> None:
        del isolated_home
        config = Config(
            provider_list=[
                _make_provider(
                    provider_name="OpenAI",
                    model_names=["gpt-5.4"],
                    disabled_models={"gpt-5.4"},
                )
            ]
        )
        with pytest.raises(ValueError, match="is disabled in provider"):
            config.get_model_config("gpt-5.4@openai")


# =============================================================================
# diagnose_model (casefold matching + availability classification)
# =============================================================================


class TestDiagnoseModelCaseInsensitive:
    @pytest.fixture
    def config(self, isolated_home: Path) -> Config:
        del isolated_home
        return Config(
            provider_list=[
                _make_provider(provider_name="OpenAI", model_names=["gpt-5.4"]),
                _make_provider(provider_name="OpenRouter", model_names=["opus"]),
            ]
        )

    def test_available_with_mixed_case_provider(self, config: Config) -> None:
        diag = config.diagnose_model("gpt-5.4@OPENAI")
        assert diag.availability == ModelAvailability.AVAILABLE
        assert diag.is_available is True
        assert diag.suggestions == []

    def test_available_with_mixed_case_provider_second_entry(self, config: Config) -> None:
        diag = config.diagnose_model("opus@OpEnRoUtEr")
        assert diag.availability == ModelAvailability.AVAILABLE

    def test_unknown_provider_is_no_matching_provider(self, config: Config) -> None:
        diag = config.diagnose_model("gpt-5.4@bogus")
        assert diag.availability == ModelAvailability.NO_MATCHING_PROVIDER
        assert "bogus" in diag.detail
