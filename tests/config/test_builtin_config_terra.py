import pytest

from klaude_code.auth.chatgpt.token_manager import ChatGPTAuthState, ChatGPTTokenManager
from klaude_code.config.builtin_config import get_builtin_config
from klaude_code.protocol import llm_param
from klaude_code.protocol.model_id import is_gpt5_plus_model


@pytest.mark.parametrize("fast", [False, True])
def test_terra_resolves_across_builtin_providers(monkeypatch: pytest.MonkeyPatch, fast: bool) -> None:
    monkeypatch.setattr(
        ChatGPTTokenManager,
        "get_state",
        lambda _: ChatGPTAuthState(
            access_token="access",
            refresh_token="refresh",
            expires_at=4102444800,
            client_id="oaiapp_test",
            scopes=["chatgpt.tokens.use.direct"],
        ),
    )
    config = get_builtin_config()
    expected_providers = ["openai", "azure-openai-responses", "chatgpt", "openrouter"]
    config.provider_list = [p for p in config.provider_list if p.provider_name in expected_providers]
    for provider in config.provider_list:
        provider.api_key = "test-key"
        provider.base_url = "https://example.com/v1"

    selector = "gpt-6.1-terra:fast" if fast else "gpt-6.1-terra"
    if fast:
        expected_providers = ["openai", "chatgpt"]
    candidates = config.iter_model_config_candidates(selector)
    assert [candidate.provider for candidate in candidates] == expected_providers
    for provider_name in expected_providers:
        resolved = config.get_model_config(f"{selector}@{provider_name}")
        prefix = "openai/" if provider_name == "openrouter" else ""
        assert resolved.model_id == f"{prefix}gpt-6.1-terra"
        assert is_gpt5_plus_model(resolved.model_id)
        assert resolved.fast_mode is fast
        assert resolved.cost == (
            llm_param.Cost(input=2, output=10, cache_read=0.1, cache_write=2.5)
            if fast
            else llm_param.Cost(input=1, output=5, cache_read=0.05, cache_write=1.25)
        )

    assert not config.iter_model_config_candidates("gpt-5.6-terra")
