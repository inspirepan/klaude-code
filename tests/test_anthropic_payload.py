from klaude_code.const import ANTHROPIC_BETA_INTERLEAVED_THINKING
from klaude_code.llm.anthropic.client import build_payload
from klaude_code.protocol import llm_param, message


def _dummy_history() -> list[message.Message]:
    return [message.UserMessage(parts=[message.TextPart(text="hi")])]


def test_build_payload_omits_empty_betas_for_adaptive_sonnet_46() -> None:
    param = llm_param.LLMCallParameter(
        input=_dummy_history(),
        model_id="claude-sonnet-4-6",
        thinking=llm_param.Thinking(type="adaptive"),
    )

    payload = build_payload(param)

    assert "betas" not in payload


def test_build_payload_includes_interleaved_beta_when_needed() -> None:
    param = llm_param.LLMCallParameter(
        input=_dummy_history(),
        model_id="claude-3-7-sonnet-20250219",
        thinking=llm_param.Thinking(type="enabled", budget_tokens=1024),
    )

    payload = build_payload(param)

    assert ANTHROPIC_BETA_INTERLEAVED_THINKING in payload.get("betas", [])
