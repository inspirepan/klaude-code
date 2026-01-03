from klaude_code.protocol.llm_param import LLMConfigModelParameter
from klaude_code.ui.common import format_model_params


def test_format_model_params_image_generation_from_modalities() -> None:
    params = LLMConfigModelParameter(modalities=["image", "text"])
    out = format_model_params(params)
    assert "image generation" in out
    assert not any(s.startswith("modalities ") for s in out)
