from typing import Any

from klaude_code.llm.openai_compatible.client import build_payload as build_openai_compatible_payload
from klaude_code.llm.openai_responses.client import build_payload as build_responses_payload
from klaude_code.protocol import llm_param


def _param(**overrides: Any) -> llm_param.LLMCallParameter:
    return llm_param.LLMCallParameter(
        input=[],
        model_id="deepseek-v4-flash",
        **overrides,
    )


def test_openai_compatible_payload_omits_unset_temperature_and_reasoning_effort() -> None:
    # Strict upstreams (e.g. opencode zen -> DeepSeek) reject explicit nulls.
    payload, _ = build_openai_compatible_payload(_param())
    assert "temperature" not in payload
    assert "reasoning_effort" not in payload


def test_openai_compatible_payload_sends_set_temperature_and_reasoning_effort() -> None:
    payload, _ = build_openai_compatible_payload(
        _param(temperature=0.5, thinking=llm_param.Thinking(reasoning_effort="low"))
    )
    assert payload["temperature"] == 0.5
    assert payload["reasoning_effort"] == "low"


def test_openai_compatible_payload_omits_null_reasoning_effort_when_thinking_unset() -> None:
    payload, _ = build_openai_compatible_payload(_param(temperature=0.5, thinking=None))
    assert payload["temperature"] == 0.5
    assert "reasoning_effort" not in payload


def test_responses_payload_omits_unset_temperature() -> None:
    payload = build_responses_payload(_param())
    assert "temperature" not in payload


def test_responses_payload_sends_set_temperature() -> None:
    payload = build_responses_payload(_param(temperature=0.5))
    assert payload["temperature"] == 0.5
