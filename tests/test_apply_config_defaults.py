import pytest

from klaude_code.llm.input_common import apply_config_defaults
from klaude_code.protocol import llm_param, message


def _dummy_history() -> list[message.Message]:
    return [message.UserMessage(parts=[message.TextPart(text="hi")])]


def test_apply_config_defaults_applies_modalities_when_missing() -> None:
    config = llm_param.LLMConfigParameter(
        protocol=llm_param.LLMClientProtocol.GOOGLE,
        model_id="gemini-3-pro-image-preview",
        modalities=["image", "text"],
    )
    param = llm_param.LLMCallParameter(input=_dummy_history())

    param = apply_config_defaults(param, config)

    assert param.modalities == ["image", "text"]


def test_apply_config_defaults_does_not_override_modalities_when_set() -> None:
    config = llm_param.LLMConfigParameter(
        protocol=llm_param.LLMClientProtocol.GOOGLE,
        model_id="gemini-3-pro-image-preview",
        modalities=["image", "text"],
    )
    param = llm_param.LLMCallParameter(input=_dummy_history(), modalities=["text"])

    param = apply_config_defaults(param, config)

    assert param.modalities == ["text"]


def test_apply_config_defaults_uses_image_config_from_model_when_missing() -> None:
    config = llm_param.LLMConfigParameter(
        protocol=llm_param.LLMClientProtocol.GOOGLE,
        model_id="gemini-3-pro-image-preview",
        image_config=llm_param.ImageConfig(image_size="4K", aspect_ratio="16:9"),
    )
    param = llm_param.LLMCallParameter(input=_dummy_history())

    param = apply_config_defaults(param, config)

    assert param.image_config is not None
    assert param.image_config.image_size == "4K"
    assert param.image_config.aspect_ratio == "16:9"


@pytest.mark.parametrize(
    ("param_cfg", "model_cfg", "expected_aspect", "expected_size"),
    [
        (
            llm_param.ImageConfig(aspect_ratio="1:1"),
            llm_param.ImageConfig(image_size="4K"),
            "1:1",
            "4K",
        ),
        (
            llm_param.ImageConfig(image_size="1K"),
            llm_param.ImageConfig(aspect_ratio="16:9"),
            "16:9",
            "1K",
        ),
        (
            llm_param.ImageConfig(image_size="2K", aspect_ratio="3:2"),
            llm_param.ImageConfig(image_size="4K", aspect_ratio="16:9"),
            "3:2",
            "2K",
        ),
    ],
)
def test_apply_config_defaults_merges_image_config_field_level(
    param_cfg: llm_param.ImageConfig,
    model_cfg: llm_param.ImageConfig,
    expected_aspect: str | None,
    expected_size: str | None,
) -> None:
    config = llm_param.LLMConfigParameter(
        protocol=llm_param.LLMClientProtocol.GOOGLE,
        model_id="gemini-3-pro-image-preview",
        image_config=model_cfg,
    )
    param = llm_param.LLMCallParameter(input=_dummy_history(), image_config=param_cfg)

    param = apply_config_defaults(param, config)

    assert param.image_config is not None
    assert param.image_config.aspect_ratio == expected_aspect
    assert param.image_config.image_size == expected_size


def test_apply_config_defaults_does_not_fill_image_config_when_model_has_none() -> None:
    config = llm_param.LLMConfigParameter(
        protocol=llm_param.LLMClientProtocol.GOOGLE,
        model_id="gemini-3-pro-image-preview",
        image_config=None,
    )
    param = llm_param.LLMCallParameter(input=_dummy_history(), image_config=llm_param.ImageConfig(aspect_ratio="1:1"))

    param = apply_config_defaults(param, config)

    assert param.image_config is not None
    assert param.image_config.aspect_ratio == "1:1"
    assert param.image_config.image_size is None
