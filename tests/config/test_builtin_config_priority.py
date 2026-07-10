from klaude_code.config.builtin_config import get_builtin_config


def test_youtu_providers_have_highest_builtin_priority() -> None:
    config = get_builtin_config()

    assert [provider.provider_name for provider in config.provider_list[:4]] == [
        "youtu-anthropic",
        "youtu-openai",
        "youtu-openai-chat",
        "youtu-gemini",
    ]
