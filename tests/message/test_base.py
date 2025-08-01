from unittest.mock import patch

import pytest

from klaudecode.message.base import Attachment, BasicMessage, count_tokens


class TestCountTokens:
    def test_count_tokens_empty_string(self):
        assert count_tokens("") == 0

    def test_count_tokens_none(self):
        assert count_tokens(None) == 0

    @patch("klaudecode.message.base._get_encoder")
    def test_count_tokens_normal_text(self, mock_get_encoder):
        mock_encoder = mock_get_encoder.return_value
        mock_encoder.encode.return_value = [1, 2, 3, 4, 5]

        result = count_tokens("Hello world")

        assert result == 5
        mock_encoder.encode.assert_called_once_with("Hello world")


class TestAttachment:
    def test_attachment_default_values(self):
        attachment = Attachment(path="/test/path")

        assert attachment.type == "text"
        assert attachment.path == "/test/path"
        assert attachment.content == ""
        assert attachment.is_directory is False
        assert attachment.line_count == 0
        assert attachment.brief == []
        assert attachment.actual_range_str == ""
        assert attachment.truncated is False
        assert attachment.media_type is None
        assert attachment.size_str == ""

    def test_attachment_text_type_get_content(self):
        attachment = Attachment(
            type="text", path="/test/file.txt", content="file content here"
        )

        content = attachment.get_content()

        assert len(content) == 1
        assert content[0]["type"] == "text"
        assert "Called the Read tool" in content[0]["text"]
        assert "/test/file.txt" in content[0]["text"]
        assert "file content here" in content[0]["text"]

    def test_attachment_directory_type_get_content(self):
        attachment = Attachment(
            type="directory", path="/test/dir", content="dir1/\ndir2/\nfile.txt"
        )

        content = attachment.get_content()

        assert len(content) == 1
        assert content[0]["type"] == "text"
        assert "Called the LS tool" in content[0]["text"]
        assert "/test/dir" in content[0]["text"]
        assert "dir1/" in content[0]["text"]

    def test_attachment_image_type_get_content_with_path(self):
        attachment = Attachment(
            type="image",
            path="/test/image.png",
            content="base64encodeddata",
            media_type="image/png",
        )

        content = attachment.get_content()

        assert len(content) == 2
        assert content[0]["type"] == "text"
        assert "/test/image.png" in content[0]["text"]
        assert content[1]["type"] == "image"
        assert content[1]["source"]["data"] == "base64encodeddata"
        assert content[1]["source"]["media_type"] == "image/png"

    def test_attachment_image_type_get_content_without_path(self):
        attachment = Attachment(
            type="image", path="", content="base64encodeddata", media_type="image/png"
        )

        content = attachment.get_content()

        assert len(content) == 1
        assert content[0]["type"] == "image"
        assert content[0]["source"]["data"] == "base64encodeddata"


class TestBasicMessage:
    def test_basic_message_default_values(self):
        msg = BasicMessage(role="test")

        assert msg.role == "test"
        assert msg.content == ""
        assert msg.removed is False
        assert msg.extra_data is None
        assert msg.attachments is None

    def test_get_content_default(self):
        msg = BasicMessage(role="test", content="Hello world")

        content = msg.get_content()

        assert len(content) == 1
        assert content[0]["type"] == "text"
        assert content[0]["text"] == "Hello world"

    def test_tokens_property_simple_text(self):
        msg = BasicMessage(role="user", content="Hello")

        with patch("klaudecode.message.base.count_tokens") as mock_count:
            mock_count.return_value = 10
            tokens = msg.tokens

            assert tokens == 10
            mock_count.assert_called_once_with("user: Hello")

    def test_tokens_property_with_complex_content(self):
        msg = BasicMessage(role="assistant")

        # Mock get_content to return a complex structure
        with patch(
            "klaudecode.message.base.BasicMessage.get_content"
        ) as mock_get_content:
            mock_get_content.return_value = [
                {"type": "text", "text": "Hello"},
                {"type": "thinking", "thinking": "Let me think"},
                {"type": "tool_use", "name": "test"},
                "plain string",
            ]

            with patch("klaudecode.message.base.count_tokens") as mock_count:
                mock_count.return_value = 20
                tokens = msg.tokens

                assert tokens == 20
                args = mock_count.call_args[0][0]
                assert "assistant:" in args
                assert "Hello" in args
                assert "Let me think" in args
                assert '"name": "test"' in args
                assert "plain string" in args

    def test_set_extra_data(self):
        msg = BasicMessage(role="test")

        msg.set_extra_data("key1", "value1")
        msg.set_extra_data("key2", "value2")

        assert msg.extra_data == {"key1": "value1", "key2": "value2"}

    def test_append_extra_data(self):
        msg = BasicMessage(role="test")

        msg.append_extra_data("list_key", "item1")
        msg.append_extra_data("list_key", "item2")

        assert msg.extra_data == {"list_key": ["item1", "item2"]}

    def test_get_extra_data(self):
        msg = BasicMessage(role="test")
        msg.set_extra_data("key1", "value1")

        assert msg.get_extra_data("key1") == "value1"
        assert msg.get_extra_data("nonexistent") is None
        assert msg.get_extra_data("nonexistent", "default") == "default"

    def test_get_extra_data_no_extra_data(self):
        msg = BasicMessage(role="test")

        assert msg.get_extra_data("key") is None
        assert msg.get_extra_data("key", "default") == "default"

    def test_append_attachment(self):
        msg = BasicMessage(role="test")
        attachment1 = Attachment(path="/test1")
        attachment2 = Attachment(path="/test2")

        msg.append_attachment(attachment1)
        msg.append_attachment(attachment2)

        assert len(msg.attachments) == 2
        assert msg.attachments[0].path == "/test1"
        assert msg.attachments[1].path == "/test2"

    def test_to_openai_not_implemented(self):
        msg = BasicMessage(role="test")

        with pytest.raises(NotImplementedError):
            msg.to_openai()

    def test_to_anthropic_not_implemented(self):
        msg = BasicMessage(role="test")

        with pytest.raises(NotImplementedError):
            msg.to_anthropic()
