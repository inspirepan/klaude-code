from klaude_code.config.builtin_config import get_builtin_config
from klaude_code.config.config import ModelConfig
from klaude_code.config.merge import _merge_model


def _find_model(provider_name: str, model_name: str) -> ModelConfig:
    config = get_builtin_config()
    for provider in config.provider_list:
        if provider.provider_name != provider_name:
            continue
        for model in provider.model_list:
            if model.model_name == model_name:
                return model
    raise AssertionError(f"model {model_name}@{provider_name} not found in builtin config")


def test_supports_vision_defaults_to_true() -> None:
    model = ModelConfig.model_validate({"model_name": "m", "model_id": "m"})
    assert model.supports_vision is True


def test_builtin_marks_glm_and_deepseek_as_non_vision() -> None:
    assert _find_model("deepseek", "deepseek-flash").supports_vision is False
    assert _find_model("deepseek", "deepseek:max").supports_vision is False
    assert _find_model("opencode-go", "glm-5.3").supports_vision is False
    assert _find_model("openrouter", "glm").supports_vision is False


def test_builtin_deepseek_vision_model_accepts_images() -> None:
    assert _find_model("deepseek", "deepseek-flash-vision").supports_vision is True
    assert _find_model("deepseek", "deepseek-flash-vision:high").supports_vision is True


def test_builtin_keeps_other_models_vision_capable() -> None:
    assert _find_model("anthropic", "sonnet").supports_vision is True
    assert _find_model("openai", "gpt-5.6-luna").supports_vision is True


def test_user_config_can_override_supports_vision_both_ways() -> None:
    builtin = ModelConfig.model_validate({"model_name": "m", "model_id": "m", "supports_vision": False})
    user_enables = ModelConfig.model_validate({"model_name": "m", "supports_vision": True})
    assert _merge_model(builtin, user_enables).supports_vision is True

    builtin_vision = ModelConfig.model_validate({"model_name": "m", "model_id": "m"})
    user_disables = ModelConfig.model_validate({"model_name": "m", "supports_vision": False})
    assert _merge_model(builtin_vision, user_disables).supports_vision is False


def test_user_config_without_field_keeps_builtin_value() -> None:
    builtin = ModelConfig.model_validate({"model_name": "m", "model_id": "m", "supports_vision": False})
    user = ModelConfig.model_validate({"model_name": "m", "max_tokens": 1000})
    merged = _merge_model(builtin, user)
    assert merged.supports_vision is False
    assert merged.max_tokens == 1000
