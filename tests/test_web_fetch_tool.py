from __future__ import annotations

import asyncio
import gzip as gzip_module
import json
import socket
import urllib.error
from pathlib import Path
from typing import cast
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
    _RETRY_HTTP_STATUS_CODES,  # pyright: ignore[reportPrivateUsage]
    _convert_html_to_markdown,  # pyright: ignore[reportPrivateUsage]
    _decode_content,  # pyright: ignore[reportPrivateUsage]
    _decompress,  # pyright: ignore[reportPrivateUsage]
    _encode_url,  # pyright: ignore[reportPrivateUsage]
    _extract_content_type_and_charset,  # pyright: ignore[reportPrivateUsage]
    _fetch_url,  # pyright: ignore[reportPrivateUsage]
    _fetch_url_with_retry,  # pyright: ignore[reportPrivateUsage]
    _format_json,  # pyright: ignore[reportPrivateUsage]
    _html_to_markdown_fallback,  # pyright: ignore[reportPrivateUsage]
    _is_pdf_url,  # pyright: ignore[reportPrivateUsage]
    _process_content,  # pyright: ignore[reportPrivateUsage]
    _strip_noise_elements,  # pyright: ignore[reportPrivateUsage]
)


def _tool_context() -> ToolContext:
    todo_context = TodoContext(get_todos=lambda: [], set_todos=lambda todos: None)
    return ToolContext(file_tracker={}, todo_context=todo_context, session_id="test", work_dir=Path("/tmp"))


class TestHelperFunctions:
    """Test helper functions for content processing."""

    def test_extract_content_type_simple(self) -> None:
        class MockResponse:
            def getheader(self, name: str, default: str = "") -> str:
                return "text/html"

        content_type, charset = _extract_content_type_and_charset(MockResponse())  # type: ignore[arg-type]
        assert content_type == "text/html"
        assert charset is None

    def test_encode_url_preserves_percent_encoded_query(self) -> None:
        url = "https://accounts.feishu.cn/accounts/page/login?redirect_uri=https%3A%2F%2Fmy.feishu.cn%2Fwiki%2Fx"
        encoded = _encode_url(url)
        assert "%253A" not in encoded
        assert "%252F" not in encoded

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


class TestFetchUrlRedirectHandling:
    def test_follow_redirect_http_errors_and_reuse_single_opener(self) -> None:
        class MockResponse:
            def __init__(self, status: int, headers: dict[str, str], data: bytes) -> None:
                self.status = status
                self._headers = headers
                self._data = data

            def getheader(self, name: str, default: str = "") -> str:
                return self._headers.get(name, default)

            def read(self, _size: int = -1) -> bytes:
                return self._data

            def close(self) -> None:
                return None

        class MockOpener:
            def __init__(self) -> None:
                self.calls = 0

            def open(self, req: object, timeout: int = 30) -> MockResponse:
                del timeout
                self.calls += 1
                url = cast(str, req.full_url)  # type: ignore[attr-defined]
                if self.calls == 1:
                    raise urllib.error.HTTPError(
                        url=url,
                        code=302,
                        msg="Found",
                        hdrs={"Location": "https://accounts.feishu.cn/login"},  # pyright: ignore[reportArgumentType]
                        fp=None,
                    )
                if self.calls == 2:
                    raise urllib.error.HTTPError(
                        url=url,
                        code=302,
                        msg="Found",
                        hdrs={"Location": "https://my.feishu.cn/wiki/doc?login_redirect_times=1"},  # pyright: ignore[reportArgumentType]
                        fp=None,
                    )
                return MockResponse(
                    status=200,
                    headers={"Content-Type": "text/plain; charset=utf-8"},
                    data=b"ok",
                )

        mock_opener = MockOpener()

        with (
            patch(
                "klaude_code.core.tool.web.web_fetch_tool.urllib.request.build_opener", return_value=mock_opener
            ) as patched_build,
            patch("klaude_code.core.tool.web.web_fetch_tool.check_ssrf", return_value=None),
        ):
            content_type, data, charset = _fetch_url("https://my.feishu.cn/wiki/doc")

        assert content_type == "text/plain"
        assert charset == "utf-8"
        assert data == b"ok"
        assert mock_opener.calls == 3
        assert patched_build.call_count == 1

    def test_too_many_redirects_returns_error(self) -> None:
        class LoopOpener:
            def open(self, req: object, timeout: int = 30) -> object:
                del timeout
                url = cast(str, req.full_url)  # type: ignore[attr-defined]
                raise urllib.error.HTTPError(
                    url=url,
                    code=302,
                    msg="Found",
                    hdrs={"Location": "https://my.feishu.cn/wiki/doc"},  # pyright: ignore[reportArgumentType]
                    fp=None,
                )

        with (
            patch("klaude_code.core.tool.web.web_fetch_tool.urllib.request.build_opener", return_value=LoopOpener()),
            patch("klaude_code.core.tool.web.web_fetch_tool.check_ssrf", return_value=None),
        ):
            try:
                _fetch_url("https://my.feishu.cn/wiki/doc", max_redirects=2)
                raise AssertionError("Expected URLError")
            except urllib.error.URLError as e:
                assert "Too many redirects" in str(e.reason)

    def test_feishu_style_multi_hop_redirect_chain(self) -> None:
        class MockResponse:
            def __init__(self, status: int, headers: dict[str, str], data: bytes) -> None:
                self.status = status
                self._headers = headers
                self._data = data

            def getheader(self, name: str, default: str = "") -> str:
                return self._headers.get(name, default)

            def read(self, _size: int = -1) -> bytes:
                return self._data

            def close(self) -> None:
                return None

        start_url = "https://my.feishu.cn/wiki/Pi3ZwnUUziWu3NkDi0acXrnInRg"
        redirects = [
            "https://accounts.feishu.cn/accounts/page/login?app_id=2&query_scope=all&redirect_uri=https%3A%2F%2Fmy.feishu.cn%2Fwiki%2FPi3ZwnUUziWu3NkDi0acXrnInRg%3Flogin_redirect_times%3D1&with_guest=1",
            "https://login.feishu.cn/accounts/trap?app_id=2&query_scope=all&redirect_uri=https%3A%2F%2Fmy.feishu.cn%2Fwiki%2FPi3ZwnUUziWu3NkDi0acXrnInRg%3Flogin_redirect_times%3D1&with_guest=1",
            "https://accounts.feishu.cn/accounts/page/login?app_id=2&no_trap=1&query_scope=all&redirect_uri=https%3A%2F%2Fmy.feishu.cn%2Fwiki%2FPi3ZwnUUziWu3NkDi0acXrnInRg%3Flogin_redirect_times%3D1&with_guest=1",
            "https://my.feishu.cn/wiki/Pi3ZwnUUziWu3NkDi0acXrnInRg?login_redirect_times=1",
            start_url,
        ]

        class MockOpener:
            def __init__(self) -> None:
                self.calls = 0
                self.requested_urls: list[str] = []

            def open(self, req: object, timeout: int = 30) -> MockResponse:
                del timeout
                self.calls += 1
                url = cast(str, req.full_url)  # type: ignore[attr-defined]
                self.requested_urls.append(url)

                if self.calls <= len(redirects):
                    raise urllib.error.HTTPError(
                        url=url,
                        code=302,
                        msg="Found",
                        hdrs={"Location": redirects[self.calls - 1]},  # pyright: ignore[reportArgumentType]
                        fp=None,
                    )

                return MockResponse(
                    status=200,
                    headers={"Content-Type": "text/html; charset=utf-8"},
                    data=b"<html><body>ok</body></html>",
                )

        mock_opener = MockOpener()

        with (
            patch("klaude_code.core.tool.web.web_fetch_tool.urllib.request.build_opener", return_value=mock_opener),
            patch("klaude_code.core.tool.web.web_fetch_tool.check_ssrf", return_value=None),
        ):
            content_type, data, charset = _fetch_url(start_url)

        assert content_type == "text/html"
        assert charset == "utf-8"
        assert data == b"<html><body>ok</body></html>"

        assert mock_opener.requested_urls == [
            start_url,
            redirects[0],
            redirects[1],
            redirects[2],
            redirects[3],
            redirects[4],
        ]

        # Ensure redirect_uri query was not double-encoded while hopping across login endpoints.
        assert "%253A" not in redirects[0]
        assert "%253A" not in mock_opener.requested_urls[1]


class TestDecompress:
    """Test gzip/deflate decompression."""

    def test_decompress_gzip(self) -> None:
        original = b"Hello, compressed world!"
        compressed = gzip_module.compress(original)
        assert _decompress(compressed, "gzip") == original

    def test_decompress_gzip_case_insensitive(self) -> None:
        original = b"case insensitive"
        compressed = gzip_module.compress(original)
        assert _decompress(compressed, "GZIP") == original

    def test_decompress_identity(self) -> None:
        data = b"plain bytes"
        assert _decompress(data, "") == data
        assert _decompress(data, "identity") == data

    def test_decompress_gzip_truncated_returns_raw(self) -> None:
        # Truncated gzip should return raw data rather than raise
        truncated = gzip_module.compress(b"full content")[:10]
        result = _decompress(truncated, "gzip")
        assert isinstance(result, bytes)

    def test_decompress_unknown_encoding_returns_raw(self) -> None:
        data = b"some data"
        assert _decompress(data, "br") == data


class TestStripNoiseElements:
    """Test script/style stripping before extraction."""

    def test_strips_script_tags(self) -> None:
        html = "<html><body><script>var x = 1;</script><p>content</p></body></html>"
        result = _strip_noise_elements(html)
        assert "var x" not in result
        assert "content" in result

    def test_strips_style_tags(self) -> None:
        html = "<html><head><style>body { color: red; }</style></head><body><p>text</p></body></html>"
        result = _strip_noise_elements(html)
        assert "color: red" not in result
        assert "text" in result

    def test_preserves_comments(self) -> None:
        html = "<!-- comment --><p>content</p>"
        result = _strip_noise_elements(html)
        assert "<!-- comment -->" in result

    def test_multiline_script(self) -> None:
        html = "<script>\nfunction foo() {\n  return 1;\n}\n</script><p>article</p>"
        result = _strip_noise_elements(html)
        assert "function foo" not in result
        assert "article" in result


class TestFetchUrlWithRetry:
    """Test retry behaviour on transient errors."""

    def _make_mock_response(self, status: int, content_type: str, data: bytes) -> object:
        class MockResponse:
            def __init__(self) -> None:
                self.status = status
                self._data = data

            def getheader(self, name: str, default: str = "") -> str:
                if name == "Content-Type":
                    return content_type
                return default

            def read(self, _size: int = -1) -> bytes:
                return self._data

            def close(self) -> None:
                pass

        return MockResponse()

    def test_retry_on_500_then_success(self) -> None:
        call_count = 0

        def fake_fetch(*_args: object, **_kwargs: object) -> tuple[str, bytes, str | None]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise urllib.error.HTTPError(
                    url="https://x.com/", code=500, msg="Internal Server Error", hdrs={}, fp=None
                )  # type: ignore[arg-type]
            return ("text/plain", b"ok", "utf-8")

        with (
            patch("klaude_code.core.tool.web.web_fetch_tool._fetch_url", side_effect=fake_fetch),
            patch("klaude_code.core.tool.web.web_fetch_tool.time.sleep"),
        ):
            _content_type, data, _charset = _fetch_url_with_retry("https://x.com/")

        assert call_count == 2
        assert data == b"ok"

    def test_no_retry_on_404(self) -> None:
        call_count = 0

        def fake_fetch(*_args: object, **_kwargs: object) -> tuple[str, bytes, str | None]:
            nonlocal call_count
            call_count += 1
            raise urllib.error.HTTPError(url="https://x.com/", code=404, msg="Not Found", hdrs={}, fp=None)  # type: ignore[arg-type]

        with patch("klaude_code.core.tool.web.web_fetch_tool._fetch_url", side_effect=fake_fetch):
            try:
                _fetch_url_with_retry("https://x.com/")
                raise AssertionError("Expected HTTPError")
            except urllib.error.HTTPError as e:
                assert e.code == 404
        assert call_count == 1

    def test_retry_on_timeout_then_success(self) -> None:
        call_count = 0

        def fake_fetch(*_args: object, **_kwargs: object) -> tuple[str, bytes, str | None]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise TimeoutError("timed out")
            return ("text/plain", b"ok", None)

        with (
            patch("klaude_code.core.tool.web.web_fetch_tool._fetch_url", side_effect=fake_fetch),
            patch("klaude_code.core.tool.web.web_fetch_tool.time.sleep"),
        ):
            _content_type, data, _charset = _fetch_url_with_retry("https://x.com/")

        assert call_count == 2
        assert data == b"ok"

    def test_retry_exhausted_raises_last_exception(self) -> None:
        def fake_fetch(*_args: object, **_kwargs: object) -> tuple[str, bytes, str | None]:
            raise urllib.error.HTTPError(url="https://x.com/", code=503, msg="Service Unavailable", hdrs={}, fp=None)  # type: ignore[arg-type]

        with (
            patch("klaude_code.core.tool.web.web_fetch_tool._fetch_url", side_effect=fake_fetch),
            patch("klaude_code.core.tool.web.web_fetch_tool.time.sleep"),
        ):
            try:
                _fetch_url_with_retry("https://x.com/")
                raise AssertionError("Expected HTTPError")
            except urllib.error.HTTPError as e:
                assert e.code == 503

    def test_retry_status_codes_include_common_server_errors(self) -> None:
        assert 500 in _RETRY_HTTP_STATUS_CODES
        assert 502 in _RETRY_HTTP_STATUS_CODES
        assert 503 in _RETRY_HTTP_STATUS_CODES
        assert 504 in _RETRY_HTTP_STATUS_CODES
        assert 404 not in _RETRY_HTTP_STATUS_CODES
        assert 429 not in _RETRY_HTTP_STATUS_CODES


class TestGzipFetchIntegration:
    """Test that gzip-compressed responses are correctly decoded end-to-end."""

    def test_fetch_url_decompresses_gzip_response(self) -> None:
        html_content = b"<html><body><p>gzip content</p></body></html>"
        compressed = gzip_module.compress(html_content)

        class MockResponse:
            status = 200
            _data = compressed

            def getheader(self, name: str, default: str = "") -> str:
                if name == "Content-Type":
                    return "text/html; charset=utf-8"
                if name == "Content-Encoding":
                    return "gzip"
                return default

            def read(self, _size: int = -1) -> bytes:
                return self._data

            def close(self) -> None:
                pass

        class MockOpener:
            def open(self, req: object, timeout: int = 30) -> MockResponse:
                del req, timeout
                return MockResponse()

        with (
            patch("klaude_code.core.tool.web.web_fetch_tool.urllib.request.build_opener", return_value=MockOpener()),
            patch("klaude_code.core.tool.web.web_fetch_tool.check_ssrf", return_value=None),
        ):
            _content_type, data, charset = _fetch_url("https://example.com/page")

        assert data == html_content
        assert charset == "utf-8"
