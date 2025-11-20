from unittest.mock import patch

from klaudecode.message.base import Attachment
from klaudecode.message.tool_call import ToolCall
from klaudecode.message.tool_result import INTERRUPTED_CONTENT, TRUNCATE_CHARS, TRUNCATE_POSTFIX, ToolMessage


class TestToolMessage:
    def test_tool_message_basic_initialization(self):
        tool_call = ToolCall(id="call_123", tool_name="test_tool")
        tool_msg = ToolMessage(
            tool_call_id="call_123",
            tool_call_cache=tool_call,
            content="Tool result content",
        )

        assert tool_msg.role == "tool"
        assert tool_msg.tool_call_id == "call_123"
        assert tool_msg.content == "Tool result content"
        assert tool_msg.error_msg is None
        assert tool_msg.system_reminders is None
        assert tool_msg.tool_call == tool_call

    def test_tool_message_with_error(self):
        tool_call = ToolCall(id="call_123", tool_name="test_tool")
        tool_msg = ToolMessage(
            tool_call_id="call_123",
            tool_call_cache=tool_call,
            content="Some content",
            error_msg="An error occurred",
        )

        assert tool_msg.error_msg == "An error occurred"

    def test_tool_message_with_system_reminders(self):
        tool_call = ToolCall(id="call_123", tool_name="test_tool")
        tool_msg = ToolMessage(
            tool_call_id="call_123",
            tool_call_cache=tool_call,
            system_reminders=["Reminder 1", "Reminder 2"],
        )

        assert tool_msg.system_reminders == ["Reminder 1", "Reminder 2"]

    def test_get_content_basic(self):
        tool_call = ToolCall(id="call_123", tool_name="test_tool", status="success")
        tool_msg = ToolMessage(
            tool_call_id="call_123",
            tool_call_cache=tool_call,
            content="Basic tool result",
        )

        content = tool_msg.get_content()

        assert len(content) == 1
        assert content[0]["type"] == "text"
        assert content[0]["text"] == "Basic tool result"

    def test_get_content_empty_content(self):
        tool_call = ToolCall(id="call_123", tool_name="test_tool", status="success")
        tool_msg = ToolMessage(tool_call_id="call_123", tool_call_cache=tool_call, content="")

        content = tool_msg.get_content()

        assert len(content) == 1
        assert content[0]["type"] == "text"
        assert "<system-reminder>Tool ran without output or errors</system-reminder>" in content[0]["text"]

    def test_get_content_truncated(self):
        tool_call = ToolCall(id="call_123", tool_name="test_tool", status="success")
        long_content = "x" * (TRUNCATE_CHARS + 1000)
        tool_msg = ToolMessage(tool_call_id="call_123", tool_call_cache=tool_call, content=long_content)

        content = tool_msg.get_content()

        assert len(content) == 1
        content_text = content[0]["text"]
        assert len(content_text) <= TRUNCATE_CHARS + len(TRUNCATE_POSTFIX) + 1  # +1 for newline
        assert TRUNCATE_POSTFIX in content_text

    def test_get_content_canceled_status(self):
        tool_call = ToolCall(id="call_123", tool_name="test_tool", status="canceled")
        tool_msg = ToolMessage(
            tool_call_id="call_123",
            tool_call_cache=tool_call,
            content="Original content",
        )

        content = tool_msg.get_content()

        assert len(content) == 1
        assert content[0]["text"] == INTERRUPTED_CONTENT

    def test_get_content_error_status(self):
        tool_call = ToolCall(id="call_123", tool_name="test_tool", status="error")
        tool_msg = ToolMessage(
            tool_call_id="call_123",
            tool_call_cache=tool_call,
            content="Some content",
            error_msg="Error details",
        )

        content = tool_msg.get_content()

        assert len(content) == 1
        content_text = content[0]["text"]
        assert "Some content" in content_text
        assert "Error: Error details" in content_text

    def test_get_content_with_attachments(self):
        tool_call = ToolCall(id="call_123", tool_name="test_tool", status="success")
        attachment = Attachment(path="/test/file.txt", content="file content")
        tool_msg = ToolMessage(
            tool_call_id="call_123",
            tool_call_cache=tool_call,
            content="Basic content",
            attachments=[attachment],
        )

        content = tool_msg.get_content()

        # Should have main content + attachment content
        assert len(content) >= 2
        assert content[0]["text"] == "Basic content"

    def test_get_content_with_system_reminders(self):
        tool_call = ToolCall(id="call_123", tool_name="test_tool", status="success")
        tool_msg = ToolMessage(
            tool_call_id="call_123",
            tool_call_cache=tool_call,
            content="Content",
            system_reminders=["Reminder 1", "Reminder 2"],
        )

        content = tool_msg.get_content()

        assert len(content) == 3  # main + 2 reminders
        assert content[0]["text"] == "Content"
        assert content[1]["text"] == "Reminder 1"
        assert content[2]["text"] == "Reminder 2"

    def test_to_openai(self):
        tool_call = ToolCall(id="call_123", tool_name="test_tool")
        tool_msg = ToolMessage(tool_call_id="call_123", tool_call_cache=tool_call, content="Result content")

        result = tool_msg.to_openai()

        assert result["role"] == "tool"
        assert result["tool_call_id"] == "call_123"
        assert "content" in result

    def test_to_anthropic(self):
        tool_call = ToolCall(id="call_123", tool_name="test_tool", status="success")
        tool_msg = ToolMessage(tool_call_id="call_123", tool_call_cache=tool_call, content="Result content")

        result = tool_msg.to_anthropic()

        assert result["role"] == "user"
        assert len(result["content"]) == 1
        assert result["content"][0]["type"] == "tool_result"
        assert result["content"][0]["tool_use_id"] == "call_123"
        assert result["content"][0]["is_error"] is False

    def test_to_anthropic_with_error(self):
        tool_call = ToolCall(id="call_123", tool_name="test_tool", status="error")
        tool_msg = ToolMessage(
            tool_call_id="call_123",
            tool_call_cache=tool_call,
            content="Error content",
            error_msg="Something went wrong",
        )

        result = tool_msg.to_anthropic()

        assert result["content"][0]["is_error"] is True

    def test_bool_with_content(self):
        tool_call = ToolCall(id="call_123", tool_name="test_tool")
        tool_msg = ToolMessage(tool_call_id="call_123", tool_call_cache=tool_call, content="Some content")

        assert bool(tool_msg) is True

    def test_bool_removed_message(self):
        tool_call = ToolCall(id="call_123", tool_name="test_tool")
        tool_msg = ToolMessage(
            tool_call_id="call_123",
            tool_call_cache=tool_call,
            content="Some content",
            removed=True,
        )

        assert bool(tool_msg) is False

    def test_set_content_normal(self):
        tool_call = ToolCall(id="call_123", tool_name="test_tool", status="processing")
        tool_msg = ToolMessage(tool_call_id="call_123", tool_call_cache=tool_call)

        tool_msg.set_content("New content")

        assert tool_msg.content == "New content"

    def test_set_content_canceled_ignored(self):
        tool_call = ToolCall(id="call_123", tool_name="test_tool", status="canceled")
        tool_msg = ToolMessage(tool_call_id="call_123", tool_call_cache=tool_call, content="Original")

        tool_msg.set_content("New content")

        assert tool_msg.content == "Original"  # Should not change

    def test_set_error_msg(self):
        tool_call = ToolCall(id="call_123", tool_name="test_tool", status="processing")
        tool_msg = ToolMessage(tool_call_id="call_123", tool_call_cache=tool_call)

        tool_msg.set_error_msg("Error occurred")

        assert tool_msg.error_msg == "Error occurred"
        assert tool_call.status == "error"

    def test_set_extra_data_normal(self):
        tool_call = ToolCall(id="call_123", tool_name="test_tool", status="processing")
        tool_msg = ToolMessage(tool_call_id="call_123", tool_call_cache=tool_call)

        tool_msg.set_extra_data("key", "value")

        assert tool_msg.get_extra_data("key") == "value"

    def test_set_extra_data_canceled_ignored(self):
        tool_call = ToolCall(id="call_123", tool_name="test_tool", status="canceled")
        tool_msg = ToolMessage(tool_call_id="call_123", tool_call_cache=tool_call)

        tool_msg.set_extra_data("key", "value")

        assert tool_msg.get_extra_data("key") is None

    def test_append_extra_data_normal(self):
        tool_call = ToolCall(id="call_123", tool_name="test_tool", status="processing")
        tool_msg = ToolMessage(tool_call_id="call_123", tool_call_cache=tool_call)

        tool_msg.append_extra_data("list_key", "item1")
        tool_msg.append_extra_data("list_key", "item2")

        assert tool_msg.get_extra_data("list_key") == ["item1", "item2"]

    def test_append_extra_data_canceled_ignored(self):
        tool_call = ToolCall(id="call_123", tool_name="test_tool", status="canceled")
        tool_msg = ToolMessage(tool_call_id="call_123", tool_call_cache=tool_call)

        tool_msg.append_extra_data("list_key", "item1")

        assert tool_msg.get_extra_data("list_key") is None

    def test_append_post_system_reminder_new_list(self):
        tool_call = ToolCall(id="call_123", tool_name="test_tool")
        tool_msg = ToolMessage(tool_call_id="call_123", tool_call_cache=tool_call)

        tool_msg.append_post_system_reminder("First reminder")

        assert tool_msg.system_reminders == ["First reminder"]

    def test_append_post_system_reminder_existing_list(self):
        tool_call = ToolCall(id="call_123", tool_name="test_tool")
        tool_msg = ToolMessage(
            tool_call_id="call_123",
            tool_call_cache=tool_call,
            system_reminders=["Existing reminder"],
        )

        tool_msg.append_post_system_reminder("New reminder")

        assert tool_msg.system_reminders == ["Existing reminder", "New reminder"]

    @patch("klaudecode.message.registry._TOOL_RESULT_RENDERERS", {})
    def test_get_suffix_renderable_no_custom_renderer_with_content(self):
        tool_call = ToolCall(id="call_123", tool_name="test_tool", status="success")
        tool_msg = ToolMessage(
            tool_call_id="call_123",
            tool_call_cache=tool_call,
            content="Some result content",
        )

        result = list(tool_msg.get_suffix_renderable())

        # Should yield one suffix with content
        assert len(result) == 1

    @patch("klaudecode.message.registry._TOOL_RESULT_RENDERERS", {})
    def test_get_suffix_renderable_no_content_success(self):
        tool_call = ToolCall(id="call_123", tool_name="test_tool", status="success")
        tool_msg = ToolMessage(tool_call_id="call_123", tool_call_cache=tool_call, content="")

        result = list(tool_msg.get_suffix_renderable())

        # Should yield "(No content)" message
        assert len(result) == 1

    def test_get_suffix_renderable_canceled_status(self):
        tool_call = ToolCall(id="call_123", tool_name="test_tool", status="canceled")
        tool_msg = ToolMessage(tool_call_id="call_123", tool_call_cache=tool_call, content="Some content")

        result = list(tool_msg.get_suffix_renderable())

        # Should include interrupted message
        assert len(result) >= 1

    def test_get_suffix_renderable_error_status(self):
        tool_call = ToolCall(id="call_123", tool_name="test_tool", status="error")
        tool_msg = ToolMessage(
            tool_call_id="call_123",
            tool_call_cache=tool_call,
            content="Content",
            error_msg="Error details",
        )

        result = list(tool_msg.get_suffix_renderable())

        # Should include error message
        assert len(result) >= 1

    def test_rich_console(self):
        tool_call = ToolCall(id="call_123", tool_name="test_tool")
        tool_msg = ToolMessage(tool_call_id="call_123", tool_call_cache=tool_call, content="Result")

        result = list(tool_msg.__rich_console__(None, None))

        # Should yield tool call and suffix
        assert len(result) >= 1
