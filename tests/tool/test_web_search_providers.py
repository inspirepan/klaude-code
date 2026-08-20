"""Parsing and chain-resolution tests for the LLM-backed web search providers."""

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
)


def _deepseek_payload() -> dict[str, Any]:
    return {
        "content": [
            {
                "type": "text",
                "text": "Here is what I found. Foo is a bar [1].",
                "citations": [
                    {"type": "web_search_result_location", "url": "https://a.com/1", "cited_text": "Foo is a bar"},
                    {"type": "web_search_result_location", "url": "https://b.com/2", "cited_text": "Second source"},
                    # First occurrence wins for duplicate URLs
                    {"type": "web_search_result_location", "url": "https://a.com/1", "cited_text": "IGNORED"},
                ],
            },
            {
                "type": "web_search_tool_result",
                "content": [
                    {"type": "web_search_result", "url": "https://a.com/1", "title": "A", "page_age": "2026-08-01"},
                    {"type": "web_search_result", "url": "https://b.com/2", "title": None, "page_age": None},
                    {"type": "web_search_result", "url": "https://a.com/1", "title": "A dup"},
                    {"type": "web_search_result", "url": "", "title": "no url, skipped"},
                ],
            },
        ]
    }


class TestDeepSeekParsing:
    def test_joins_citations_and_dedupes_by_url(self) -> None:
        outcome = _parse_deepseek_response(_deepseek_payload(), 10)

        assert outcome.answer == "Here is what I found. Foo is a bar [1]."
        assert len(outcome.results) == 2

        first, second = outcome.results
        assert first.url == "https://a.com/1"
        assert first.title == "A"
        assert first.snippet == "Foo is a bar"
        assert first.published == "2026-08-01"
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

    def test_no_result_blocks_is_an_error(self) -> None:
        payload = {"content": [{"type": "text", "text": "I made this up without searching."}]}
        with pytest.raises(SearchProviderError):
            _parse_deepseek_response(payload, 10)

    def test_snippet_length_capped(self) -> None:
        payload = {
            "content": [
                {
                    "type": "text",
                    "text": "answer",
                    "citations": [{"url": "https://a.com", "cited_text": "x" * (WEB_SEARCH_SNIPPET_MAX_CHARS + 100)}],
                },
                {
                    "type": "web_search_tool_result",
                    "content": [{"type": "web_search_result", "url": "https://a.com", "title": "A"}],
                },
            ]
        }
        outcome = _parse_deepseek_response(payload, 10)
        assert len(outcome.results[0].snippet) == WEB_SEARCH_SNIPPET_MAX_CHARS


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
