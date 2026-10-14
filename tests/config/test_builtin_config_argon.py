from klaude_code.config.builtin_config import get_builtin_config
from klaude_code.protocol import llm_param


def test_argon_resolves_all_tiers_without_replacing_flash_or_pro() -> None:
    config = get_builtin_config()
    expected_providers = ["youtu-gemini", "google", "google-vertex", "openrouter"]
    config.provider_list = [p for p in config.provider_list if p.provider_name in expected_providers]
    for provider in config.provider_list:
        provider.api_key = "test-key"
        provider.google_application_credentials = "fake.json"
        provider.google_cloud_project = "test-project"
        provider.google_cloud_location = "global"

    for suffix, effort in [("", "medium"), (":low", "low"), (":high", "high")]:
        candidates = config.iter_model_config_candidates(f"gemini-4-argon{suffix}")
        assert [candidate.provider for candidate in candidates] == expected_providers
        for provider_name in expected_providers:
            resolved = config.get_model_config(f"gemini-4-argon{suffix}@{provider_name}")
            assert config.get_model_config(f"argon{suffix}@{provider_name}") == resolved
            prefix = "google/" if provider_name == "openrouter" else ""
            assert resolved.model_id == f"{prefix}gemini-4-argon"
            assert resolved.context_limit == 1048576
            assert resolved.max_tokens == 65536
            assert resolved.supports_vision
            assert resolved.thinking is not None
            assert resolved.thinking.reasoning_effort == effort
            assert resolved.thinking.budget_tokens is None
            assert resolved.cost == llm_param.Cost(input=2, output=10, cache_read=0.1)
            assert config.get_model_config(f"gemini-flash@{provider_name}").model_id == f"{prefix}gemini-3.8-flash"
            assert config.get_model_config(f"gemini-pro@{provider_name}").model_id == f"{prefix}gemini-3.1-pro-preview"
