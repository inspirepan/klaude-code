"""Integration tests for Brave LLM Context API search backend.

Requires BRAVE_API_KEY environment variable to be set.
Run with: make test-network
"""

import os

import pytest

from klaude_code.core.tool.web.web_search_tool import SearchResult, _format_results, _search_brave


@pytest.mark.network
class TestBraveSearch:
    @pytest.fixture(autouse=True)
    def _require_api_key(self) -> None:
        if not os.environ.get("BRAVE_API_KEY"):
            pytest.skip("BRAVE_API_KEY not set")

    def test_search_returns_results(self) -> None:
        results = _search_brave("Python programming language", 5, os.environ["BRAVE_API_KEY"])
        assert len(results) > 0
        assert all(isinstance(r, SearchResult) for r in results)

    def test_result_fields_populated(self) -> None:
        results = _search_brave("what is rust programming", 3, os.environ["BRAVE_API_KEY"])
        assert len(results) > 0
        first = results[0]
        assert first.url.startswith("http")
        assert first.title
        assert first.snippet
        assert first.position == 1

    def test_positions_sequential(self) -> None:
        results = _search_brave("machine learning", 5, os.environ["BRAVE_API_KEY"])
        for i, r in enumerate(results):
            assert r.position == i + 1

    def test_format_results_xml(self) -> None:
        results = _search_brave("Python asyncio", 3, os.environ["BRAVE_API_KEY"])
        formatted = _format_results(results)
        assert formatted.startswith("<search_results>")
        assert formatted.endswith("</search_results>")
        assert "<title>" in formatted
        assert "<url>" in formatted
        assert "<snippet>" in formatted
        for r in results:
            assert f'<result position="{r.position}">' in formatted
