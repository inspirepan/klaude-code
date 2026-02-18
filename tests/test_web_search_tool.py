from __future__ import annotations

import asyncio
import os
from collections.abc import Iterator
from unittest.mock import patch

import pytest

from klaude_code.core.tool import WebSearchTool
from klaude_code.core.tool.context import TodoContext, ToolContext
from klaude_code.core.tool.web.external_content import (
    _BOUNDARY_END,  # pyright: ignore[reportPrivateUsage]
    _BOUNDARY_START,  # pyright: ignore[reportPrivateUsage]
)
from klaude_code.core.tool.web.web_cache import _cache as web_cache  # pyright: ignore[reportPrivateUsage]
from klaude_code.core.tool.web.web_search_tool import SearchResult


def _tool_context() -> ToolContext:
    todo_context = TodoContext(get_todos=lambda: [], set_todos=lambda todos: None)
    return ToolContext(file_tracker={}, todo_context=todo_context, session_id="test")


@pytest.fixture(autouse=True)
def _no_brave_api_key() -> Iterator[None]:  # pyright: ignore[reportUnusedFunction]
    with patch.dict(os.environ, {"BRAVE_API_KEY": ""}):
        yield


def _fake_search(_query: str, _max_results: int) -> list[SearchResult]:
    return [
        SearchResult(title="Result 1", url="https://example.com/1", snippet="First result", position=1),
        SearchResult(title="Result 2", url="https://example.com/2", snippet="Second result", position=2),
    ]


class TestWebSearchSecurity:
    def test_results_wrapped_with_boundary(self) -> None:
        web_cache.clear()
        with patch("klaude_code.core.tool.web.web_search_tool._search_duckduckgo", side_effect=_fake_search):
            args = WebSearchTool.WebSearchArguments(query="test query").model_dump_json()
            result = asyncio.run(WebSearchTool.call(args, _tool_context()))
            assert result.status == "success"
            assert result.output_text is not None
            assert _BOUNDARY_START in result.output_text
            assert _BOUNDARY_END in result.output_text

    def test_no_security_warning(self) -> None:
        """Web search results should NOT include the security warning (only boundary markers)."""
        web_cache.clear()
        with patch("klaude_code.core.tool.web.web_search_tool._search_duckduckgo", side_effect=_fake_search):
            args = WebSearchTool.WebSearchArguments(query="another query").model_dump_json()
            result = asyncio.run(WebSearchTool.call(args, _tool_context()))
            assert result.status == "success"
            assert result.output_text is not None
            assert "SECURITY NOTICE" not in result.output_text

    def test_search_results_in_output(self) -> None:
        web_cache.clear()
        with patch("klaude_code.core.tool.web.web_search_tool._search_duckduckgo", side_effect=_fake_search):
            args = WebSearchTool.WebSearchArguments(query="find results").model_dump_json()
            result = asyncio.run(WebSearchTool.call(args, _tool_context()))
            assert result.status == "success"
            assert result.output_text is not None
            assert "<search_results>" in result.output_text
            assert "Result 1" in result.output_text


class TestWebSearchCaching:
    def test_cache_hit(self) -> None:
        web_cache.clear()
        call_count = 0

        def counting_search(query: str, max_results: int) -> list[SearchResult]:
            nonlocal call_count
            call_count += 1
            return _fake_search(query, max_results)

        with patch("klaude_code.core.tool.web.web_search_tool._search_duckduckgo", side_effect=counting_search):
            args = WebSearchTool.WebSearchArguments(query="cached search").model_dump_json()
            r1 = asyncio.run(WebSearchTool.call(args, _tool_context()))
            r2 = asyncio.run(WebSearchTool.call(args, _tool_context()))
            assert r1.status == "success"
            assert r2.status == "success"
            assert call_count == 1

    def test_different_queries_not_cached(self) -> None:
        web_cache.clear()
        call_count = 0

        def counting_search(query: str, max_results: int) -> list[SearchResult]:
            nonlocal call_count
            call_count += 1
            return _fake_search(query, max_results)

        with patch("klaude_code.core.tool.web.web_search_tool._search_duckduckgo", side_effect=counting_search):
            args1 = WebSearchTool.WebSearchArguments(query="query one").model_dump_json()
            args2 = WebSearchTool.WebSearchArguments(query="query two").model_dump_json()
            asyncio.run(WebSearchTool.call(args1, _tool_context()))
            asyncio.run(WebSearchTool.call(args2, _tool_context()))
            assert call_count == 2
