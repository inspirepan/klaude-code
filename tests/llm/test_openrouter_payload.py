import pytest

from klaude_code.llm.openrouter.client import build_payload
from klaude_code.protocol import llm_param, message


@pytest.mark.parametrize(
    "model_id",
    ["anthropic/claude-opus-4.7", "anthropic/claude-opus-4.8", "anthropic/claude-opus-5"],
)
def test_build_payload_omits_temperature_for_new_opus_models(model_id: str) -> None:
    param = llm_param.LLMCallParameter(
        input=[message.UserMessage(parts=[message.TextPart(text="hi")])],
        model_id=model_id,
        temperature=0.2,
    )

    payload, _, _ = build_payload(param)

    assert "temperature" not in payload
