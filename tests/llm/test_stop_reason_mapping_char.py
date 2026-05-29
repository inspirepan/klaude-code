"""Characterization tests for per-provider stop-reason / finish-reason mappings.

These lock in the EXACT StopReason returned for every input string each provider
mapping function currently handles, plus the None fallback for unknown inputs.
They protect a future unification of these maps into a shared table.

Do NOT change these assertions to reflect "desired" behavior; they encode the
behavior as it exists today.
"""

from __future__ import annotations

import pytest

from klaude_code.llm.anthropic.client import _map_anthropic_stop_reason
from klaude_code.llm.bedrock_anthropic.client import _map_bedrock_stop_reason
from klaude_code.llm.google.client import _map_finish_reason as _map_google_finish_reason
from klaude_code.llm.openai_compatible.stream import _map_finish_reason as _map_openai_finish_reason

# --- Anthropic --------------------------------------------------------------

ANTHROPIC_CASES = {
    "end_turn": "stop",
    "stop_sequence": "stop",
    "max_tokens": "length",
    "tool_use": "tool_use",
    "content_filter": "error",
    "error": "error",
    "cancelled": "aborted",
    "canceled": "aborted",
    "aborted": "aborted",
}


@pytest.mark.parametrize(("reason", "expected"), sorted(ANTHROPIC_CASES.items()))
def test_anthropic_stop_reason_mapping(reason: str, expected: str) -> None:
    assert _map_anthropic_stop_reason(reason) == expected


@pytest.mark.parametrize("reason", ["", "unknown", "END_TURN", "Stop", "refusal", "pause_turn"])
def test_anthropic_stop_reason_unknown_returns_none(reason: str) -> None:
    # Anthropic mapping is case-sensitive and returns None for anything unmapped.
    assert _map_anthropic_stop_reason(reason) is None


# --- Bedrock ----------------------------------------------------------------

BEDROCK_CASES = {
    "end_turn": "stop",
    "stop_sequence": "stop",
    "max_tokens": "length",
    "model_context_window_exceeded": "length",
    "tool_use": "tool_use",
    "content_filtered": "error",
    "guardrail_intervened": "error",
    "malformed_model_output": "error",
    "malformed_tool_use": "error",
}


@pytest.mark.parametrize(("reason", "expected"), sorted(BEDROCK_CASES.items()))
def test_bedrock_stop_reason_mapping(reason: str, expected: str) -> None:
    assert _map_bedrock_stop_reason(reason) == expected


@pytest.mark.parametrize("reason", ["", "unknown", "cancelled", "aborted", "END_TURN"])
def test_bedrock_stop_reason_unknown_returns_none(reason: str) -> None:
    # Note: bedrock does NOT map cancelled/aborted (unlike anthropic/google).
    assert _map_bedrock_stop_reason(reason) is None


def test_bedrock_stop_reason_none_input_returns_none() -> None:
    # _map_bedrock_stop_reason accepts None and treats it as "".
    assert _map_bedrock_stop_reason(None) is None


# --- Google -----------------------------------------------------------------

GOOGLE_CASES = {
    "stop": "stop",
    "end_turn": "stop",
    "max_tokens": "length",
    "length": "length",
    "tool_use": "tool_use",
    "safety": "error",
    "recitation": "error",
    "other": "error",
    "content_filter": "error",
    "blocked": "error",
    "blocklist": "error",
    "language": "error",
    "prohibited_content": "error",
    "spii": "error",
    "malformed_function_call": "error",
    "malformed_response": "error",
    "unexpected_tool_call": "error",
    "image_safety": "error",
    "image_prohibited_content": "error",
    "no_image": "error",
    "image_recitation": "error",
    "image_other": "error",
    "cancelled": "aborted",
    "canceled": "aborted",
    "aborted": "aborted",
}


@pytest.mark.parametrize(("reason", "expected"), sorted(GOOGLE_CASES.items()))
def test_google_finish_reason_mapping(reason: str, expected: str) -> None:
    assert _map_google_finish_reason(reason) == expected


@pytest.mark.parametrize(
    ("reason", "expected"),
    [
        ("STOP", "stop"),  # normalized to lowercase
        ("  SAFETY  ", "error"),  # stripped + lowercased
        ("Tool_Use", "tool_use"),
        ("MALFORMED_RESPONSE", "error"),
    ],
)
def test_google_finish_reason_normalizes_case_and_whitespace(reason: str, expected: str) -> None:
    assert _map_google_finish_reason(reason) == expected


@pytest.mark.parametrize("reason", ["", "finish_reason_unspecified", "totally_unknown"])
def test_google_finish_reason_unknown_returns_none(reason: str) -> None:
    assert _map_google_finish_reason(reason) is None


# --- OpenAI-compatible (chat completions) -----------------------------------

OPENAI_CASES = {
    "stop": "stop",
    "length": "length",
    "tool_calls": "tool_use",
    "content_filter": "error",
    "error": "error",
    "cancelled": "aborted",
}


@pytest.mark.parametrize(("reason", "expected"), sorted(OPENAI_CASES.items()))
def test_openai_compatible_finish_reason_mapping(reason: str, expected: str) -> None:
    assert _map_openai_finish_reason(reason) == expected


@pytest.mark.parametrize(
    "reason",
    ["", "STOP", "tool_use", "function_call", "canceled", "aborted", "max_tokens"],
)
def test_openai_compatible_finish_reason_unknown_returns_none(reason: str) -> None:
    # Case-sensitive; note "tool_use" is NOT mapped here (only "tool_calls"),
    # and "canceled"/"aborted" are NOT mapped (only "cancelled").
    assert _map_openai_finish_reason(reason) is None
