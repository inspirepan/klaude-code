from __future__ import annotations

from klaude_code.llm.stream_parts import (
    append_text_part,
    append_thinking_text_part,
    build_partial_message,
    build_partial_parts,
    degrade_thinking_to_text,
)
from klaude_code.protocol import message


def test_append_text_part_merges_consecutive_text() -> None:
    parts: list[message.Part] = []

    assert append_text_part(parts, "hello") == 0
    assert parts == [message.TextPart(text="hello")]

    assert append_text_part(parts, " world") == 0
    assert parts == [message.TextPart(text="hello world")]


def test_append_text_part_appends_after_non_text() -> None:
    parts: list[message.Part] = [message.ThinkingTextPart(text="t", model_id="m")]

    assert append_text_part(parts, "x") == 1
    assert isinstance(parts[1], message.TextPart)
    assert parts[1].text == "x"


def test_append_thinking_text_part_merges_by_default() -> None:
    parts: list[message.Part] = []

    assert append_thinking_text_part(parts, "a", model_id="m") == 0
    assert isinstance(parts[0], message.ThinkingTextPart)
    assert parts[0].text == "a"
    assert parts[0].model_id == "m"

    assert append_thinking_text_part(parts, "b", model_id="m") == 0
    assert isinstance(parts[0], message.ThinkingTextPart)
    assert parts[0].text == "ab"


def test_append_thinking_text_part_force_new_creates_new_part() -> None:
    parts: list[message.Part] = [message.ThinkingTextPart(text="a", model_id="m")]

    assert append_thinking_text_part(parts, "b", model_id="m", force_new=True) == 1
    assert len(parts) == 2
    assert isinstance(parts[0], message.ThinkingTextPart)
    assert isinstance(parts[1], message.ThinkingTextPart)
    assert parts[0].text == "a"
    assert parts[1].text == "b"


def test_degrade_thinking_to_text_drops_signatures_and_wraps_thinking() -> None:
    parts: list[message.Part] = [
        message.ThinkingTextPart(text="think", model_id="m"),
        message.ThinkingSignaturePart(signature="sig", model_id="m", format="x"),
        message.TextPart(text="answer"),
    ]

    degraded = degrade_thinking_to_text(parts)
    assert len(degraded) == 2
    assert isinstance(degraded[0], message.TextPart)
    assert degraded[0].text.startswith("<thinking>\nthink\n</thinking>")
    assert degraded[0].text.endswith("\n\n")
    assert degraded[1] == message.TextPart(text="answer")


def test_build_partial_parts_filters_tool_calls_and_keeps_images() -> None:
    parts: list[message.Part] = [
        message.ThinkingTextPart(text="think", model_id="m"),
        message.ToolCallPart(call_id="c", tool_name="Bash", arguments_json="{}"),
        message.ImageFilePart(file_path="/tmp/x.png"),
        message.TextPart(text="ok"),
    ]

    partial = build_partial_parts(parts)
    assert all(not isinstance(p, message.ToolCallPart) for p in partial)
    assert any(isinstance(p, message.ImageFilePart) for p in partial)
    assert any(isinstance(p, message.TextPart) and p.text == "ok" for p in partial)


def test_build_partial_message_returns_none_when_only_tool_calls() -> None:
    parts: list[message.Part] = [
        message.ToolCallPart(call_id="c", tool_name="Bash", arguments_json="{}"),
    ]

    assert build_partial_message(parts, response_id="r") is None


def test_build_partial_message_sets_aborted_and_preserves_response_id() -> None:
    parts: list[message.Part] = [message.TextPart(text="hi")]

    msg = build_partial_message(parts, response_id="r")
    assert msg is not None
    assert msg.response_id == "r"
    assert msg.stop_reason == "aborted"
    assert msg.parts == [message.TextPart(text="hi")]
