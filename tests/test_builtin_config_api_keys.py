from klaude_code.config.builtin_config import SUPPORTED_API_KEYS


def test_supported_api_keys_include_recent_providers() -> None:
    env_vars = {item.env_var for item in SUPPORTED_API_KEYS}

    assert "OPENCODE_API_KEY" in env_vars
    assert "CEREBRAS_API_KEY" in env_vars
    assert "ARK_API_KEY" in env_vars
    assert "BRAVE_API_KEY" in env_vars


def test_supported_api_keys_have_unique_env_vars() -> None:
    env_vars = [item.env_var for item in SUPPORTED_API_KEYS]
    assert len(env_vars) == len(set(env_vars))
