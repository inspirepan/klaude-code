from __future__ import annotations

import asyncio
import json

import pytest

from klaude_code.core.tool import WebFetchTool
from klaude_code.core.tool.context import TodoContext, ToolContext
from klaude_code.core.tool.web.web_fetch_tool import (
    _convert_html_to_markdown,  # pyright: ignore[reportPrivateUsage]
    _decode_content,  # pyright: ignore[reportPrivateUsage]
    _extract_content_type_and_charset,  # pyright: ignore[reportPrivateUsage]
    _format_json,  # pyright: ignore[reportPrivateUsage]
    _is_pdf_url,  # pyright: ignore[reportPrivateUsage]
    _process_content,  # pyright: ignore[reportPrivateUsage]
)


def _tool_context() -> ToolContext:
    todo_context = TodoContext(get_todos=lambda: [], set_todos=lambda todos: None)
    return ToolContext(file_tracker={}, todo_context=todo_context, session_id="test")


class TestHelperFunctions:
    """Test helper functions for content processing."""

    def test_extract_content_type_simple(self) -> None:
        class MockResponse:
            def getheader(self, name: str, default: str = "") -> str:
                return "text/html"

        content_type, charset = _extract_content_type_and_charset(MockResponse())  # type: ignore[arg-type]
        assert content_type == "text/html"
        assert charset is None

    def test_extract_content_type_with_charset(self) -> None:
        class MockResponse:
            def getheader(self, name: str, default: str = "") -> str:
                return "text/html; charset=utf-8"

        content_type, charset = _extract_content_type_and_charset(MockResponse())  # type: ignore[arg-type]
        assert content_type == "text/html"
        assert charset == "utf-8"

    def test_extract_content_type_empty(self) -> None:
        class MockResponse:
            def getheader(self, name: str, default: str = "") -> str:
                return default

        content_type, charset = _extract_content_type_and_charset(MockResponse())  # type: ignore[arg-type]
        assert content_type == ""
        assert charset is None

    def test_decode_content_utf8(self) -> None:
        data = b"Hello World"
        result = _decode_content(data, "utf-8")
        assert result == "Hello World"

    def test_decode_content_gbk(self) -> None:
        data = "Chinese".encode("gbk")
        result = _decode_content(data, "gbk")
        assert result == "Chinese"

    def test_decode_content_auto_detect(self) -> None:
        data = b"Hello"
        result = _decode_content(data, None)
        assert result == "Hello"

    def test_decode_content_fallback(self) -> None:
        # Invalid UTF-8 bytes should be replaced, not raise error
        data = b"\xff\xfe invalid bytes"
        result = _decode_content(data, None)
        assert isinstance(result, str)

    def test_format_json_valid(self) -> None:
        input_json = '{"name":"test","value":123}'
        result = _format_json(input_json)
        expected = json.dumps({"name": "test", "value": 123}, indent=2, ensure_ascii=False)
        assert result == expected

    def test_format_json_invalid(self) -> None:
        invalid_json = "not valid json"
        result = _format_json(invalid_json)
        assert result == invalid_json

    def test_process_content_json(self) -> None:
        input_json = '{"key":"value"}'
        result = _process_content("application/json", input_json)
        assert '"key": "value"' in result

    def test_process_content_text_json(self) -> None:
        input_json = '{"key":"value"}'
        result = _process_content("text/json", input_json)
        assert '"key": "value"' in result

    def test_process_content_markdown(self) -> None:
        markdown = "# Hello\n\nThis is markdown."
        result = _process_content("text/markdown", markdown)
        assert result == markdown

    def test_process_content_unknown(self) -> None:
        content = "Some plain text content"
        result = _process_content("text/plain", content)
        assert result == content

    def test_convert_html_to_markdown_simple(self) -> None:
        html = "<html><body><h1>Title</h1><p>Paragraph text.</p></body></html>"
        result = _convert_html_to_markdown(html)
        # trafilatura may return empty for minimal HTML, just check it doesn't crash
        assert isinstance(result, str)

    def test_is_pdf_url_with_extension(self) -> None:
        assert _is_pdf_url("https://example.com/paper.pdf") is True
        assert _is_pdf_url("https://example.com/paper.PDF") is True
        assert _is_pdf_url("https://example.com/dir/file.pdf?query=1") is True

    def test_is_pdf_url_with_pdf_path(self) -> None:
        # arxiv style URLs
        assert _is_pdf_url("https://arxiv.org/pdf/2512.24880") is True
        assert _is_pdf_url("https://arxiv.org/pdf/2512.24880v1") is True

    def test_is_pdf_url_negative(self) -> None:
        assert _is_pdf_url("https://example.com/page.html") is False
        assert _is_pdf_url("https://example.com/api/pdf_info") is False


class TestWebFetchTool:
    """Test WebFetchTool class."""

    def test_schema(self) -> None:
        schema = WebFetchTool.schema()
        assert schema.name == "WebFetch"
        assert "url" in schema.parameters["properties"]
        assert schema.parameters["required"] == ["url"]

    def test_invalid_url_no_protocol(self) -> None:
        args = WebFetchTool.WebFetchArguments(url="example.com").model_dump_json()
        result = asyncio.run(WebFetchTool.call(args, _tool_context()))
        assert result.status == "error"
        assert result.output_text is not None
        assert "http://" in result.output_text or "https://" in result.output_text

    def test_invalid_arguments(self) -> None:
        result = asyncio.run(WebFetchTool.call("not valid json", _tool_context()))
        assert result.status == "error"
        assert result.output_text is not None
        assert "Invalid arguments" in result.output_text


@pytest.mark.network
class TestWebFetchToolNetwork:
    """Network-dependent tests for WebFetchTool."""

    def test_fetch_real_url(self) -> None:
        """Test fetching a real URL (Claude Code docs)."""
        args = WebFetchTool.WebFetchArguments(url="https://code.claude.com/docs/en/hooks").model_dump_json()
        result = asyncio.run(WebFetchTool.call(args, _tool_context()))

        assert result.status == "success"
        assert result.output_text is not None
        assert len(result.output_text) > 0
        # The page should contain content about hooks
        output_lower = result.output_text.lower()
        assert "hook" in output_lower or "claude" in output_lower

    def test_fetch_nonexistent_domain(self) -> None:
        """Test fetching from a nonexistent domain."""
        args = WebFetchTool.WebFetchArguments(
            url="https://this-domain-definitely-does-not-exist-12345.com/page"
        ).model_dump_json()
        result = asyncio.run(WebFetchTool.call(args, _tool_context()))

        assert result.status == "error"

    def test_fetch_pdf_url(self) -> None:
        """Test fetching a PDF file (arxiv)."""
        args = WebFetchTool.WebFetchArguments(url="https://arxiv.org/pdf/2312.00752").model_dump_json()
        result = asyncio.run(WebFetchTool.call(args, _tool_context()))

        assert result.status == "success"
        assert result.output_text is not None
        assert "PDF file saved to:" in result.output_text
        assert ".pdf" in result.output_text

    # def test_fetch_404_page(self) -> None:
    #     """Test fetching a page that returns 404."""
    #     args = WebFetchTool.WebFetchArguments(url="https://httpbin.org/status/404").model_dump_json()
    #     result = asyncio.run(WebFetchTool.call(args))

    #     assert result.status == "error"
    #     assert result.output is not None
    #     assert "404" in result.output
