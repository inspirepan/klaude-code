"""Tests for tool message formatting across chat-completions providers."""

from typing import Any, cast

from openai.types import chat

from klaude_code.llm.input_common import DeveloperAttachment, build_tool_message, build_tool_message_for_chat_completions
from klaude_code.llm.openrouter.input import (  # pyright: ignore[reportPrivateUsage]
    _add_cache_control,
    _rewrite_tool_message_for_claude,
    convert_history_to_input,
)
from klaude_code.protocol import message


def _make_tool_result(
    output: str = "ok", call_id: str = "call_1", parts: list[message.Part] | None = None
) -> message.ToolResultMessage:
    return message.ToolResultMessage(status="success", output_text=output, call_id=call_id, parts=parts or [])


def _empty_attachment() -> DeveloperAttachment:
    return DeveloperAttachment()


def _content_parts(msg: dict[str, object]) -> list[dict[str, Any]]:
    content = msg["content"]
    assert isinstance(content, list)
    return cast(list[dict[str, Any]], content)


def _as_messages(msgs: list[dict[str, object]]) -> list[chat.ChatCompletionMessageParam]:
    return cast(list[chat.ChatCompletionMessageParam], msgs)


def test_chat_completions_tool_message_content_is_string() -> None:
    msg = _make_tool_result("hello world")
    tool_msg, _ = build_tool_message_for_chat_completions(msg, _empty_attachment())

    assert tool_msg["content"] == "hello world"


def test_chat_completions_tool_message_empty_output_still_string() -> None:
    msg = _make_tool_result("   ")
    tool_msg, _ = build_tool_message_for_chat_completions(msg, _empty_attachment())

    assert tool_msg["content"] == "   "


def test_build_tool_message_content_is_list() -> None:
    msg = _make_tool_result("some output")
    tool_msg = build_tool_message(msg, _empty_attachment())
    parts = _content_parts(tool_msg)

    assert parts[0] == {"type": "text", "text": "some output"}


def test_rewrite_tool_message_for_claude_converts_string_to_list() -> None:
    msg = _make_tool_result("result text")
    tool_msg, _ = build_tool_message_for_chat_completions(msg, _empty_attachment())

    _rewrite_tool_message_for_claude(tool_msg, add_cache_control=True)

    parts = _content_parts(tool_msg)
    assert parts == [{"type": "text", "text": "result text", "cache_control": {"type": "ephemeral"}}]


def test_add_cache_control_attaches_to_tool_message_list() -> None:
    tool_msg: dict[str, object] = {
        "role": "tool",
        "content": [{"type": "text", "text": "result text"}],
        "tool_call_id": "call_1",
    }

    _add_cache_control(_as_messages([tool_msg]), use_cache_control=True)

    parts = _content_parts(tool_msg)
    assert parts[-1].get("cache_control") == {"type": "ephemeral"}


def test_add_cache_control_attaches_to_last_tool_in_sequence() -> None:
    user_msg: dict[str, object] = {"role": "user", "content": [{"type": "text", "text": "hi"}]}
    tool_msg_1: dict[str, object] = {
        "role": "tool",
        "content": [{"type": "text", "text": "first"}],
        "tool_call_id": "call_1",
    }
    tool_msg_2: dict[str, object] = {
        "role": "tool",
        "content": [{"type": "text", "text": "second"}],
        "tool_call_id": "call_2",
    }
    assistant_msg: dict[str, object] = {"role": "assistant", "content": "thinking..."}

    _add_cache_control(_as_messages([user_msg, assistant_msg, tool_msg_1, tool_msg_2]), use_cache_control=True)

    parts_2 = _content_parts(tool_msg_2)
    assert parts_2[-1].get("cache_control") == {"type": "ephemeral"}
    parts_1 = _content_parts(tool_msg_1)
    assert "cache_control" not in parts_1[-1]


def test_add_cache_control_noop_when_disabled() -> None:
    tool_msg: dict[str, object] = {
        "role": "tool",
        "content": [{"type": "text", "text": "result"}],
        "tool_call_id": "call_1",
    }

    _add_cache_control(_as_messages([tool_msg]), use_cache_control=False)

    parts = _content_parts(tool_msg)
    assert "cache_control" not in parts[-1]


def test_openrouter_non_claude_keeps_tool_content_as_string() -> None:
    history: list[message.Message] = [_make_tool_result("plain tool result")]

    messages = convert_history_to_input(history, model_name="gpt-5.4")

    assert messages[0]["role"] == "tool"
    assert messages[0]["content"] == "plain tool result"


def test_openrouter_claude_rewrites_tool_content_to_list_with_cache_control() -> None:
    history: list[message.Message] = [_make_tool_result("claude tool result")]

    messages = convert_history_to_input(history, model_name="anthropic/claude-3-7-sonnet")

    assert messages[0]["role"] == "tool"
    assert messages[0]["content"] == [
        {"type": "text", "text": "claude tool result", "cache_control": {"type": "ephemeral"}}
    ]


def test_openrouter_claude_with_tool_images_keeps_tool_list_and_user_image_message() -> None:
    history: list[message.Message] = [
        _make_tool_result(
            "rendered",
            parts=[message.ImageURLPart(url="data:image/png;base64,AA==", id=None)],
        )
    ]

    messages = convert_history_to_input(history, model_name="anthropic/claude-3-7-sonnet")

    assert messages[0]["role"] == "tool"
    assert messages[0]["content"] == [{"type": "text", "text": "rendered"}]
    assert messages[1]["role"] == "user"
    assert messages[1]["content"] == [
        {"type": "text", "text": "Attached image(s) from tool result:"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,AA=="}},
    ]
