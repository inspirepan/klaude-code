"""Parsing and request tests for web search providers."""

from __future__ import annotations

import io
import json
import urllib.error
from email.message import Message
from typing import Any
from unittest.mock import patch

import pytest

from klaude_code.const import WEB_SEARCH_SNIPPET_MAX_CHARS
from klaude_code.tool.web import web_search_tool
from klaude_code.tool.web.web_search_tool import (
    SearchProviderError,
    SearchResult,
    _fetch_json,  # pyright: ignore[reportPrivateUsage]
    _format_results,  # pyright: ignore[reportPrivateUsage]
    _parse_deepseek_response,  # pyright: ignore[reportPrivateUsage]
    _parse_openai_response,  # pyright: ignore[reportPrivateUsage]
    _parse_parallel_response,  # pyright: ignore[reportPrivateUsage]
    _search_deepseek,  # pyright: ignore[reportPrivateUsage]
    _search_parallel,  # pyright: ignore[reportPrivateUsage]
)


def _deepseek_payload() -> dict[str, Any]:
    return {
        "results": [
            {
                "url": "https://a.com/1",
                "title": "A",
                "summary": "Foo is a bar",
                "snippet": "Short snippet",
                "date": "2026-08-01T00:00:00+00:00",
            },
            {"url": "https://b.com/2", "title": None, "summary": "", "snippet": "Second source", "date": None},
            {"url": "https://a.com/1", "title": "A dup", "summary": "IGNORED"},
            {"url": "", "title": "no url, skipped"},
        ]
    }


class TestDeepSeekParsing:
    def test_prefers_summary_and_dedupes_by_url(self) -> None:
        outcome = _parse_deepseek_response(_deepseek_payload(), 10)

        assert outcome.answer is None
        assert len(outcome.results) == 2

        first, second = outcome.results
        assert first.url == "https://a.com/1"
        assert first.title == "A"
        assert first.snippet == "Foo is a bar"
        assert first.published == "2026-08-01T00:00:00+00:00"
        assert first.position == 1

        assert second.url == "https://b.com/2"
        assert second.title == ""
        assert second.snippet == "Second source"
        assert second.published is None
        assert second.position == 2

    def test_truncates_and_repositions(self) -> None:
        outcome = _parse_deepseek_response(_deepseek_payload(), 1)
        assert len(outcome.results) == 1
        assert outcome.results[0].position == 1

    def test_empty_results_are_a_normal_search_outcome(self) -> None:
        assert _parse_deepseek_response({"results": []}, 10).results == []

    def test_snippet_length_capped(self) -> None:
        payload = {
            "results": [
                {
                    "url": "https://a.com",
                    "summary": "x" * (WEB_SEARCH_SNIPPET_MAX_CHARS + 100),
                },
            ]
        }
        outcome = _parse_deepseek_response(payload, 10)
        assert len(outcome.results[0].snippet) == WEB_SEARCH_SNIPPET_MAX_CHARS


class TestDeepSeekRequest:
    @pytest.mark.parametrize(
        "base_url",
        [None, "https://api.deepseek.com", "https://api.deepseek.com/v1/", "https://api.deepseek.com/anthropic"],
    )
    def test_uses_standalone_api_and_bearer_auth(self, base_url: str | None) -> None:
        with patch.object(web_search_tool, "_fetch_json", return_value=_deepseek_payload()) as fetch:
            _search_deepseek("DeepSeek site:github.com", 5, "ds-key", base_url)

        req, timeout = fetch.call_args.args
        assert req.full_url == "https://api.deepseek.com/v1/tools/search"
        assert req.get_method() == "POST"
        assert req.get_header("Authorization") == "Bearer ds-key"
        assert req.get_header("Anthropic-version") is None
        assert json.loads(req.data) == {"query": "DeepSeek site:github.com", "count": 5, "need_content": False}
        assert timeout == 30

    def test_custom_base_url_is_preserved(self) -> None:
        with patch.object(web_search_tool, "_fetch_json", return_value=_deepseek_payload()) as fetch:
            _search_deepseek("test", 5, "ds-key", "https://proxy.example/deepseek")
        assert fetch.call_args.args[0].full_url == "https://proxy.example/deepseek/v1/tools/search"

    def test_query_length_limit_uses_unicode_characters(self) -> None:
        with patch.object(web_search_tool, "_fetch_json", return_value=_deepseek_payload()) as fetch:
            _search_deepseek("\u641c" * 128, 5, "ds-key", None)
            fetch.assert_called_once()
            with pytest.raises(SearchProviderError, match="128"):
                _search_deepseek("\u641c" * 129, 5, "ds-key", None)
            fetch.assert_called_once()


def _openai_payload() -> dict[str, Any]:
    text = "Alpha claims beta [a]. Gamma says delta [b]."
    #                    0123456789012345678901234567890123456789012
    return {
        "output": [
            {"type": "web_search_call", "id": "ws_1", "status": "completed", "action": {"type": "search"}},
            {
                "type": "message",
                "role": "assistant",
                "content": [
                    {
                        "type": "output_text",
                        "text": text,
                        "annotations": [
                            {
                                "type": "url_citation",
                                "url": "https://a.com",
                                "title": "A",
                                "start_index": 0,
                                "end_index": 5,
                            },
                            {
                                "type": "url_citation",
                                "url": "https://b.com",
                                "title": None,
                                "start_index": 23,
                                "end_index": 28,
                            },
                            {"type": "url_citation", "url": "https://a.com", "title": "dup"},
                            {"type": "file_citation", "url": "https://ignored.com"},
                        ],
                    }
                ],
            },
        ]
    }


class TestOpenAIParsing:
    def test_sources_from_annotations_with_cited_span_snippet(self) -> None:
        outcome = _parse_openai_response(_openai_payload(), 10)

        assert outcome.answer == "Alpha claims beta [a]. Gamma says delta [b]."
        assert len(outcome.results) == 2

        first, second = outcome.results
        assert first.url == "https://a.com"
        assert first.title == "A"
        assert first.snippet == "Alpha"
        assert first.position == 1

        assert second.url == "https://b.com"
        assert second.title == ""
        assert second.snippet == "Gamma"
        assert second.position == 2

    def test_no_citations_is_an_error(self) -> None:
        payload = {
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": "No search needed for this.", "annotations": []}],
                }
            ]
        }
        with pytest.raises(SearchProviderError):
            _parse_openai_response(payload, 10)


def _parallel_payload() -> dict[str, Any]:
    return {
        "search_id": "search_1",
        "results": [
            {
                "url": "https://a.com/1",
                "title": "A",
                "publish_date": "2026-08-01",
                "excerpts": ["first excerpt", "second excerpt"],
            },
            {"url": "https://b.com/2", "title": None, "publish_date": None, "excerpts": []},
            {"url": "", "title": "no url, skipped", "excerpts": ["x"]},
        ],
    }


class TestParallelParsing:
    def test_joins_excerpts_and_reads_publish_date(self) -> None:
        outcome = _parse_parallel_response(_parallel_payload(), 10)

        # Parallel returns excerpts only, never a generated answer.
        assert outcome.answer is None
        assert len(outcome.results) == 2

        first, second = outcome.results
        assert first.url == "https://a.com/1"
        assert first.title == "A"
        assert first.snippet == "first excerpt\nsecond excerpt"
        assert first.published == "2026-08-01"
        assert first.position == 1

        assert second.url == "https://b.com/2"
        assert second.title == ""
        assert second.snippet == ""
        assert second.published is None
        assert second.position == 2

    def test_truncates_and_repositions(self) -> None:
        outcome = _parse_parallel_response(_parallel_payload(), 1)
        assert len(outcome.results) == 1
        assert outcome.results[0].position == 1

    def test_no_results_is_an_error(self) -> None:
        with pytest.raises(SearchProviderError):
            _parse_parallel_response({"results": []}, 10)

    def test_snippet_length_capped(self) -> None:
        payload = {"results": [{"url": "https://a.com", "excerpts": ["x" * (WEB_SEARCH_SNIPPET_MAX_CHARS + 100)]}]}
        outcome = _parse_parallel_response(payload, 10)
        assert len(outcome.results[0].snippet) == WEB_SEARCH_SNIPPET_MAX_CHARS


class TestParallelRequest:
    def test_uses_fast_mode_and_x_api_key_header(self) -> None:
        captured: dict[str, Any] = {}

        def _capture(req: Any, _timeout: int) -> dict[str, Any]:
            captured["url"] = req.full_url
            captured["headers"] = req.headers
            captured["body"] = json.loads(req.data)
            return _parallel_payload()

        with patch.object(web_search_tool, "_fetch_json", side_effect=_capture):
            _search_parallel("rust async runtimes", 5, "parallel-key")

        assert captured["url"] == "https://api.parallel.ai/v1/search"
        assert captured["headers"]["X-api-key"] == "parallel-key"
        assert captured["body"] == {
            "mode": "fast",
            "objective": "rust async runtimes",
            "search_queries": ["rust async runtimes"],
            "advanced_settings": {"max_results": 5},
        }


class TestFormatResults:
    def test_answer_block_and_optional_tags(self) -> None:
        results = [
            SearchResult(title="T", url="https://a.com", snippet="s", published="2026-08-01", position=1),
            SearchResult(title="", url="https://b.com/path", snippet="", position=2),
        ]
        formatted = _format_results(results, answer="the answer")
        assert formatted.startswith("<answer>\nthe answer\n</answer>\n<search_results>")
        assert "<published>2026-08-01</published>" in formatted
        # Empty title falls back to the URL hostname; empty snippet tag omitted.
        assert "<title>b.com</title>" in formatted
        assert formatted.count("<snippet>") == 1

    def test_empty_results_keeps_no_results_message(self) -> None:
        formatted = _format_results([], answer="answer only")
        assert formatted.startswith("<answer>")
        assert "No results were found" in formatted


class TestFetchJson:
    def test_http_error_maps_to_provider_error_with_detail(self) -> None:
        req = web_search_tool.urllib.request.Request("https://example.com", data=b"{}")
        body = json.dumps({"error": {"message": "bad key"}}).encode()
        error = urllib.error.HTTPError("https://example.com", 401, "Unauthorized", Message(), io.BytesIO(body))
        with (
            patch.object(web_search_tool._opener, "open", side_effect=error),  # pyright: ignore[reportPrivateUsage]
            pytest.raises(SearchProviderError, match="HTTP 401: bad key"),
        ):
            _fetch_json(req, 1)

    def test_redirects_are_not_followed(self) -> None:
        handler = web_search_tool._NoRedirectHandler()  # pyright: ignore[reportPrivateUsage]
        req = web_search_tool.urllib.request.Request("https://example.com")
        assert handler.redirect_request(req, None, 302, "Found", Message(), "https://evil.com") is None
