from typing import Any

import pytest

from klaude_code.llm.openai_compatible.client import build_payload as build_openai_compatible_payload
from klaude_code.llm.openai_responses.client import build_payload as build_responses_payload
from klaude_code.protocol import llm_param, message


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


@pytest.mark.parametrize(
    "parts",
    [
        [],
        [message.TextPart(text="")],
        [message.ThinkingTextPart(text="unfinished", reasoning_field="reasoning_content")],
        [message.ThinkingTextPart(text="unfinished", reasoning_field="reasoning_details")],
    ],
    ids=["empty", "empty-text", "reasoning-content", "reasoning-details"],
)
def test_openai_compatible_payload_skips_invalid_assistant_turns_without_mutating_history(
    parts: list[message.Part],
) -> None:
    thinking = message.ThinkingTextPart(text="plan", reasoning_field="reasoning_content")
    param = llm_param.LLMCallParameter(
        model_id="deepseek-v4-flash",
        input=[
            message.UserMessage(parts=[message.TextPart(text="start")]),
            message.AssistantMessage(parts=parts),
            message.UserMessage(parts=[message.TextPart(text="continue")]),
            message.AssistantMessage(
                parts=[
                    thinking,
                    message.ToolCallPart(call_id="call_1", tool_name="Bash", arguments_json="{}"),
                ]
            ),
            message.ToolResultMessage(call_id="call_1", tool_name="Bash", output_text="done", status="success"),
            message.AssistantMessage(parts=[thinking, message.TextPart(text="finished")]),
        ],
    )
    original = param.model_copy(deep=True)

    payload, _ = build_openai_compatible_payload(param)

    messages = list(payload["messages"])
    assert [item["role"] for item in messages] == ["user", "user", "assistant", "tool", "assistant"]
    assert messages[2] == {
        "role": "assistant",
        "reasoning_content": "plan",
        "tool_calls": [{"id": "call_1", "type": "function", "function": {"name": "Bash", "arguments": "{}"}}],
    }
    assert messages[3] == {"role": "tool", "tool_call_id": "call_1", "content": "done"}
    assert messages[4] == {"role": "assistant", "reasoning_content": "plan", "content": "finished"}
    assert param == original


def test_responses_payload_omits_unset_temperature() -> None:
    payload = build_responses_payload(_param())
    assert "temperature" not in payload


def test_responses_payload_sends_set_temperature() -> None:
    payload = build_responses_payload(_param(temperature=0.5))
    assert payload["temperature"] == 0.5
