from klaude_code.config.builtin_config import get_builtin_config


def test_youtu_anthropic_has_highest_builtin_priority() -> None:
    config = get_builtin_config()

    assert config.provider_list[0].provider_name == "youtu-anthropic"
    assert not {"youtu-openai", "youtu-gemini"} & {provider.provider_name for provider in config.provider_list}
    assert not any(model.model_name.startswith("kimi") for model in config.provider_list[0].model_list)
