"""Tests for tool message list-format content and _add_cache_control compatibility."""

from typing import Any, cast

from openai.types import chat

from klaude_code.llm.input_common import (
    DeveloperAttachment,
    build_tool_message,
    build_tool_message_for_chat_completions,
)
from klaude_code.llm.openrouter.input import _add_cache_control  # pyright: ignore[reportPrivateUsage]
from klaude_code.protocol import message


def _make_tool_result(output: str = "ok", call_id: str = "call_1") -> message.ToolResultMessage:
    return message.ToolResultMessage(status="success", output_text=output, call_id=call_id)


def _empty_attachment() -> DeveloperAttachment:
    return DeveloperAttachment()


def _content_parts(msg: dict[str, object]) -> list[dict[str, Any]]:
    """Extract content as a list of dicts, with proper typing for test assertions."""
    content = msg["content"]
    assert isinstance(content, list)
    return cast(list[dict[str, Any]], content)


# --- build_tool_message_for_chat_completions produces list content ---


def test_chat_completions_tool_message_content_is_list() -> None:
    msg = _make_tool_result("hello world")
    tool_msg, _ = build_tool_message_for_chat_completions(msg, _empty_attachment())
    parts = _content_parts(tool_msg)
    assert len(parts) == 1
    assert parts[0] == {"type": "text", "text": "hello world"}


def test_chat_completions_tool_message_empty_output_still_list() -> None:
    """When output is whitespace-only, content should still be a list with empty text."""
    msg = _make_tool_result("   ")
    tool_msg, _ = build_tool_message_for_chat_completions(msg, _empty_attachment())
    parts = _content_parts(tool_msg)
    assert parts[0]["type"] == "text"
    assert parts[0]["text"] == ""


# --- build_tool_message (non-chat-completions) also produces list content ---


def test_build_tool_message_content_is_list() -> None:
    msg = _make_tool_result("some output")
    tool_msg = build_tool_message(msg, _empty_attachment())
    parts = _content_parts(tool_msg)
    assert parts[0] == {"type": "text", "text": "some output"}


# --- _add_cache_control integration ---


def _as_messages(msgs: list[dict[str, object]]) -> list[chat.ChatCompletionMessageParam]:
    return cast(list[chat.ChatCompletionMessageParam], msgs)


def test_add_cache_control_attaches_to_tool_message() -> None:
    """_add_cache_control should attach cache_control to the last text part
    of a tool message built by build_tool_message_for_chat_completions."""
    msg = _make_tool_result("result text")
    tool_msg, _ = build_tool_message_for_chat_completions(msg, _empty_attachment())

    _add_cache_control(_as_messages([tool_msg]), use_cache_control=True)

    parts = _content_parts(tool_msg)
    assert parts[-1].get("cache_control") == {"type": "ephemeral"}


def test_add_cache_control_attaches_to_last_tool_in_sequence() -> None:
    """When multiple messages exist, cache_control goes on the last user/tool message."""
    user_msg: dict[str, object] = {"role": "user", "content": [{"type": "text", "text": "hi"}]}
    tool_msg_1, _ = build_tool_message_for_chat_completions(_make_tool_result("first", "call_1"), _empty_attachment())
    tool_msg_2, _ = build_tool_message_for_chat_completions(_make_tool_result("second", "call_2"), _empty_attachment())
    assistant_msg: dict[str, object] = {"role": "assistant", "content": "thinking..."}

    _add_cache_control(_as_messages([user_msg, assistant_msg, tool_msg_1, tool_msg_2]), use_cache_control=True)

    # cache_control should be on tool_msg_2 (the last tool message)
    parts_2 = _content_parts(tool_msg_2)
    assert parts_2[-1].get("cache_control") == {"type": "ephemeral"}
    # and NOT on tool_msg_1
    parts_1 = _content_parts(tool_msg_1)
    assert "cache_control" not in parts_1[-1]


def test_add_cache_control_noop_when_disabled() -> None:
    msg = _make_tool_result("result")
    tool_msg, _ = build_tool_message_for_chat_completions(msg, _empty_attachment())

    _add_cache_control(_as_messages([tool_msg]), use_cache_control=False)

    parts = _content_parts(tool_msg)
    assert "cache_control" not in parts[-1]
