from pathlib import Path

import pytest

from klaude_code.config.builtin_config import get_builtin_config
from klaude_code.protocol import llm_param


def test_haiku_resolves_to_55_on_every_existing_provider(isolated_home: Path) -> None:
    del isolated_home
    config = get_builtin_config()
    expected_ids = {
        "youtu-anthropic": "claude-haiku-5-5",
        "anthropic": "claude-haiku-5-5",
        "aws-bedrock": "global.anthropic.claude-haiku-5-5",
        "openrouter": "anthropic/claude-haiku-5.5",
    }
    config.provider_list = [
        provider
        for provider in config.provider_list
        if any(model.model_name == "haiku" for model in provider.model_list)
    ]
    assert {provider.provider_name for provider in config.provider_list} == set(expected_ids)
    for provider in config.provider_list:
        provider.api_key = "test-key"
        provider.aws_access_key = "test-access-key"
        provider.aws_secret_key = "test-secret-key"
        provider.aws_region = "us-east-1"

    candidates = config.iter_model_config_candidates("haiku")
    assert [candidate.provider for candidate in candidates] == list(expected_ids)
    for provider_name, model_id in expected_ids.items():
        resolved = config.get_model_config(f"haiku@{provider_name}")
        assert resolved.model_id == model_id
        assert config.get_model_config(f"claude-haiku-5-5@{provider_name}") == resolved
        assert resolved.context_limit == 1000000
        assert resolved.max_tokens == 128000
        assert resolved.supports_vision
        assert resolved.effort == "low"
        assert resolved.thinking == llm_param.Thinking(type="adaptive")
        assert resolved.cost == llm_param.Cost(input=0.1, output=0.5, cache_read=0.01, cache_write=0.125)
        for old_alias in ("claude-haiku-4-5", "claude-haiku-4-5-20251001", "anthropic/claude-haiku-4.5"):
            with pytest.raises(ValueError, match="Unknown model"):
                config.get_model_config(f"{old_alias}@{provider_name}")
