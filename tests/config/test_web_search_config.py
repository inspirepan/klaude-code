"""Tests for the web_search config section: builtin defaults, merge, and save."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
import yaml

import klaude_code.config.config as _config_module
from klaude_code.config.builtin_config import get_builtin_config
from klaude_code.config.config import (
    UserConfig,
    WebSearchConfig,
    WebSearchProviderConfig,
    default_web_search_config,
)
from klaude_code.config.merge import merge_configs


class TestBuiltinDefaults:
    def test_yaml_defaults_match_code_defaults(self) -> None:
        """Guard against drift between builtin_config.yaml and default_web_search_config()."""
        assert get_builtin_config().web_search == default_web_search_config()

    def test_default_chain_order(self) -> None:
        providers = [p.provider for p in default_web_search_config().providers]
        assert providers == ["exa", "brave", "deepseek", "openai"]


class TestWebSearchMerge:
    def test_no_user_config_uses_builtin(self) -> None:
        merged = merge_configs(None, get_builtin_config())
        assert merged.web_search == default_web_search_config()
        # The merged chain must be a copy, not the builtin's own list.
        assert merged.web_search is not get_builtin_config().web_search

    def test_user_list_replaces_membership_and_order(self) -> None:
        user = UserConfig(
            web_search=WebSearchConfig(
                providers=[
                    WebSearchProviderConfig(provider="openai"),
                    WebSearchProviderConfig(provider="brave"),
                ]
            )
        )
        merged = merge_configs(user, get_builtin_config())
        assert [p.provider for p in merged.web_search.providers] == ["openai", "brave"]

    def test_unset_fields_inherit_from_builtin(self) -> None:
        user = UserConfig(
            web_search=WebSearchConfig(
                providers=[
                    WebSearchProviderConfig(provider="deepseek", model="deepseek-v4-pro"),
                ]
            )
        )
        merged = merge_configs(user, get_builtin_config())
        entry = merged.web_search.providers[0]
        assert entry.model == "deepseek-v4-pro"
        assert entry.api_key == "${DEEPSEEK_API_KEY}"
        assert entry.base_url == "https://api.deepseek.com/anthropic"

    def test_empty_web_search_section_inherits_builtin(self) -> None:
        """A bare `web_search: {}` in the YAML is not an override; builtin chain applies."""
        user = UserConfig.model_validate({"web_search": {}})
        merged = merge_configs(user, get_builtin_config())
        assert merged.web_search == default_web_search_config()

    def test_explicit_empty_providers_disables_search(self) -> None:
        """An explicit `providers: []` means the user opted out of web search."""
        user = UserConfig.model_validate({"web_search": {"providers": []}})
        merged = merge_configs(user, get_builtin_config())
        assert merged.web_search.providers == []


class TestWebSearchSave:
    def test_save_writes_web_search_override(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        test_config_path = tmp_path / "test-config.yaml"
        monkeypatch.setattr(_config_module, "config_path", test_config_path)

        config = merge_configs(None, get_builtin_config())
        config.web_search = WebSearchConfig(
            providers=[
                WebSearchProviderConfig(provider="openai"),
                WebSearchProviderConfig(provider="brave"),
            ]
        )
        asyncio.run(config.save())

        saved = yaml.safe_load(test_config_path.read_text())
        providers = saved["web_search"]["providers"]
        # Only the fields the user effectively set are persisted; the rest
        # inherit from builtin at load time.
        assert providers == [{"provider": "openai"}, {"provider": "brave"}]

        # Roundtrip: loading the saved file reproduces the override with inheritance.
        reloaded_user = UserConfig.model_validate(saved)
        remerged = merge_configs(reloaded_user, get_builtin_config())
        assert [p.provider for p in remerged.web_search.providers] == ["openai", "brave"]
        assert remerged.web_search.providers[0].api_key == "${OPENAI_API_KEY}"

    def test_save_omits_web_search_when_matching_builtin(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        test_config_path = tmp_path / "test-config.yaml"
        monkeypatch.setattr(_config_module, "config_path", test_config_path)

        config = merge_configs(None, get_builtin_config())
        config.main_model = "test-model"
        asyncio.run(config.save())

        saved = yaml.safe_load(test_config_path.read_text())
        assert "web_search" not in saved
