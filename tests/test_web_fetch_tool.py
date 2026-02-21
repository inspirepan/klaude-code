from __future__ import annotations

import asyncio
import json
import socket
from unittest.mock import patch

from klaude_code.core.tool import WebFetchTool
from klaude_code.core.tool.context import TodoContext, ToolContext
from klaude_code.core.tool.web.external_content import (
    _BOUNDARY_END,  # pyright: ignore[reportPrivateUsage]
    _BOUNDARY_START,  # pyright: ignore[reportPrivateUsage]
)
from klaude_code.core.tool.web.web_cache import _cache as web_cache  # pyright: ignore[reportPrivateUsage]
from klaude_code.core.tool.web.web_fetch_tool import (
    _READABILITY_MAX_HTML_CHARS,  # pyright: ignore[reportPrivateUsage]
    _convert_html_to_markdown,  # pyright: ignore[reportPrivateUsage]
    _decode_content,  # pyright: ignore[reportPrivateUsage]
    _extract_content_type_and_charset,  # pyright: ignore[reportPrivateUsage]
    _format_json,  # pyright: ignore[reportPrivateUsage]
    _html_to_markdown_fallback,  # pyright: ignore[reportPrivateUsage]
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

    def test_convert_html_to_markdown_fallback_on_large_html(self) -> None:
        """HTML exceeding _READABILITY_MAX_HTML_CHARS should bypass trafilatura."""
        body_text = "Important content here. " * 100
        html = f"<html><body><p>{body_text}</p></body></html>"
        # Pad to exceed threshold
        padding = "<!-- padding -->" * ((_READABILITY_MAX_HTML_CHARS // 16) + 1)
        large_html = html + padding
        assert len(large_html) > _READABILITY_MAX_HTML_CHARS

        result = _convert_html_to_markdown(large_html)
        assert "Important content here." in result

    def test_convert_html_to_markdown_fallback_on_trafilatura_empty(self) -> None:
        """When trafilatura returns None/empty, should fall back to regex stripping."""
        html = "<html><body><span>tiny</span></body></html>"
        with patch("trafilatura.extract", return_value=None):
            result = _convert_html_to_markdown(html)
        assert "tiny" in result

    def test_html_to_markdown_fallback_strips_scripts_and_styles(self) -> None:
        html = (
            "<html><head><style>body{color:red}</style></head>"
            "<body><script>alert('xss')</script>"
            "<p>Real content</p></body></html>"
        )
        result = _html_to_markdown_fallback(html)
        assert "Real content" in result
        assert "alert" not in result
        assert "color:red" not in result

    def test_html_to_markdown_fallback_decodes_entities(self) -> None:
        html = "<p>A &amp; B &lt; C &gt; D &quot;E&quot; &#39;F&#39;</p>"
        result = _html_to_markdown_fallback(html)
        assert "A & B < C > D \"E\" 'F'" in result

    def test_html_to_markdown_fallback_collapses_newlines(self) -> None:
        html = "<p>First</p><p></p><p></p><p></p><p>Second</p>"
        result = _html_to_markdown_fallback(html)
        assert "\n\n\n" not in result
        assert "First" in result
        assert "Second" in result

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

    def test_ssrf_blocks_localhost(self) -> None:
        args = WebFetchTool.WebFetchArguments(url="http://localhost:8080/secret").model_dump_json()
        result = asyncio.run(WebFetchTool.call(args, _tool_context()))
        assert result.status == "error"
        assert result.output_text is not None
        assert "Blocked" in result.output_text or "security policy" in result.output_text

    def test_ssrf_blocks_private_ip(self) -> None:
        args = WebFetchTool.WebFetchArguments(url="http://10.0.0.1/internal").model_dump_json()
        result = asyncio.run(WebFetchTool.call(args, _tool_context()))
        assert result.status == "error"
        assert result.output_text is not None
        assert "security policy" in result.output_text

    def test_ssrf_blocks_metadata_endpoint(self) -> None:
        args = WebFetchTool.WebFetchArguments(url="http://169.254.169.254/latest/meta-data/").model_dump_json()
        result = asyncio.run(WebFetchTool.call(args, _tool_context()))
        assert result.status == "error"
        assert result.output_text is not None
        assert "security policy" in result.output_text

    def test_ssrf_blocks_dns_to_private(self) -> None:
        """Domain that resolves to a private IP should be blocked."""
        fake_addrinfo = [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("127.0.0.1", 0))]
        with patch("klaude_code.core.tool.web.ssrf.socket.getaddrinfo", return_value=fake_addrinfo):
            args = WebFetchTool.WebFetchArguments(url="http://evil.example.com/steal").model_dump_json()
            result = asyncio.run(WebFetchTool.call(args, _tool_context()))
            assert result.status == "error"
            assert result.output_text is not None
            assert "security policy" in result.output_text

    def test_security_wrapping_present(self) -> None:
        """Successful fetch should wrap content with security boundaries."""
        web_cache.clear()

        def fake_fetch(*_args: object, **_kwargs: object) -> tuple[str, bytes, str | None]:
            return ("text/plain", b"Hello from the web", "utf-8")

        with patch("klaude_code.core.tool.web.web_fetch_tool._fetch_url", side_effect=fake_fetch):
            args = WebFetchTool.WebFetchArguments(url="https://example.com/page").model_dump_json()
            result = asyncio.run(WebFetchTool.call(args, _tool_context()))
            assert result.status == "success"
            assert result.output_text is not None
            assert _BOUNDARY_START in result.output_text
            assert _BOUNDARY_END in result.output_text
            assert "SECURITY NOTICE" in result.output_text

    def test_caching(self) -> None:
        """Second call for same URL should return cached result."""
        web_cache.clear()
        call_count = 0

        def fake_fetch(*_args: object, **_kwargs: object) -> tuple[str, bytes, str | None]:
            nonlocal call_count
            call_count += 1
            return ("text/plain", b"cached content", "utf-8")

        with patch("klaude_code.core.tool.web.web_fetch_tool._fetch_url", side_effect=fake_fetch):
            args = WebFetchTool.WebFetchArguments(url="https://example.com/cached").model_dump_json()
            result1 = asyncio.run(WebFetchTool.call(args, _tool_context()))
            result2 = asyncio.run(WebFetchTool.call(args, _tool_context()))
            assert result1.status == "success"
            assert result2.status == "success"
            assert call_count == 1  # Only fetched once
