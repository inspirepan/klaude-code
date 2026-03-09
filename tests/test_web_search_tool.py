from __future__ import annotations

import asyncio
import os
from collections.abc import Iterator
from pathlib import Path
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
    return ToolContext(file_tracker={}, todo_context=todo_context, session_id="test", work_dir=Path("/tmp"))


@pytest.fixture(autouse=True)
def _no_web_search_api_keys() -> Iterator[None]:  # pyright: ignore[reportUnusedFunction]
    with patch.dict(os.environ, {"BRAVE_API_KEY": "", "EXA_API_KEY": ""}):
        yield


def _fake_search(_query: str, _max_results: int) -> list[SearchResult]:
    return [
        SearchResult(title="Result 1", url="https://example.com/1", snippet="First result", position=1),
        SearchResult(title="Result 2", url="https://example.com/2", snippet="Second result", position=2),
    ]


def _fake_brave(query: str, max_results: int, _api_key: str) -> list[SearchResult]:
    return _fake_search(query, max_results)


def _fake_exa(query: str, max_results: int, _api_key: str) -> list[SearchResult]:
    return _fake_search(query, max_results)


class TestWebSearchSecurity:
    def test_results_wrapped_with_boundary(self) -> None:
        web_cache.clear()
        with (
            patch("klaude_code.core.tool.web.web_search_tool.get_auth_env", return_value="brave-auth-key"),
            patch("klaude_code.core.tool.web.web_search_tool._search_brave", side_effect=_fake_brave),
        ):
            args = WebSearchTool.WebSearchArguments(query="test query").model_dump_json()
            result = asyncio.run(WebSearchTool.call(args, _tool_context()))
            assert result.status == "success"
            assert result.output_text is not None
            assert _BOUNDARY_START in result.output_text
            assert _BOUNDARY_END in result.output_text

    def test_no_security_warning(self) -> None:
        """Web search results should NOT include the security warning (only boundary markers)."""
        web_cache.clear()
        with (
            patch("klaude_code.core.tool.web.web_search_tool.get_auth_env", return_value="brave-auth-key"),
            patch("klaude_code.core.tool.web.web_search_tool._search_brave", side_effect=_fake_brave),
        ):
            args = WebSearchTool.WebSearchArguments(query="another query").model_dump_json()
            result = asyncio.run(WebSearchTool.call(args, _tool_context()))
            assert result.status == "success"
            assert result.output_text is not None
            assert "SECURITY NOTICE" not in result.output_text

    def test_search_results_in_output(self) -> None:
        web_cache.clear()
        with (
            patch("klaude_code.core.tool.web.web_search_tool.get_auth_env", return_value="brave-auth-key"),
            patch("klaude_code.core.tool.web.web_search_tool._search_brave", side_effect=_fake_brave),
        ):
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

        def counting_search(query: str, max_results: int, _api_key: str) -> list[SearchResult]:
            nonlocal call_count
            call_count += 1
            return _fake_search(query, max_results)

        with (
            patch("klaude_code.core.tool.web.web_search_tool.get_auth_env", return_value="brave-auth-key"),
            patch("klaude_code.core.tool.web.web_search_tool._search_brave", side_effect=counting_search),
        ):
            args = WebSearchTool.WebSearchArguments(query="cached search").model_dump_json()
            r1 = asyncio.run(WebSearchTool.call(args, _tool_context()))
            r2 = asyncio.run(WebSearchTool.call(args, _tool_context()))
            assert r1.status == "success"
            assert r2.status == "success"
            assert call_count == 1

    def test_different_queries_not_cached(self) -> None:
        web_cache.clear()
        call_count = 0

        def counting_search(query: str, max_results: int, _api_key: str) -> list[SearchResult]:
            nonlocal call_count
            call_count += 1
            return _fake_search(query, max_results)

        with (
            patch("klaude_code.core.tool.web.web_search_tool.get_auth_env", return_value="brave-auth-key"),
            patch("klaude_code.core.tool.web.web_search_tool._search_brave", side_effect=counting_search),
        ):
            args1 = WebSearchTool.WebSearchArguments(query="query one").model_dump_json()
            args2 = WebSearchTool.WebSearchArguments(query="query two").model_dump_json()
            asyncio.run(WebSearchTool.call(args1, _tool_context()))
            asyncio.run(WebSearchTool.call(args2, _tool_context()))
            assert call_count == 2


class TestBraveApiKeySelection:
    def test_returns_error_when_both_brave_and_exa_keys_missing(self) -> None:
        web_cache.clear()

        with patch("klaude_code.core.tool.web.web_search_tool.get_auth_env", return_value=""):
            args = WebSearchTool.WebSearchArguments(query="missing key").model_dump_json()
            result = asyncio.run(WebSearchTool.call(args, _tool_context()))

        assert result.status == "error"
        assert (
            result.output_text == "Search failed: missing BRAVE_API_KEY or EXA_API_KEY. Please set one and try again."
        )

    def test_uses_auth_env_brave_key_when_process_env_missing(self) -> None:
        web_cache.clear()

        with (
            patch(
                "klaude_code.core.tool.web.web_search_tool.get_auth_env",
                return_value="brave-auth-key",
            ) as mock_get_auth_env,
            patch(
                "klaude_code.core.tool.web.web_search_tool._search_brave",
                side_effect=_fake_brave,
            ) as mock_search_brave,
        ):
            args = WebSearchTool.WebSearchArguments(query="use brave from auth env").model_dump_json()
            result = asyncio.run(WebSearchTool.call(args, _tool_context()))

        assert result.status == "success"
        mock_get_auth_env.assert_called_once_with("BRAVE_API_KEY")
        mock_search_brave.assert_called_once()
        assert mock_search_brave.call_args.args[2] == "brave-auth-key"

    def test_process_env_brave_key_takes_precedence_over_auth_env(self) -> None:
        web_cache.clear()

        with (
            patch.dict(os.environ, {"BRAVE_API_KEY": "brave-env-key"}),
            patch(
                "klaude_code.core.tool.web.web_search_tool.get_auth_env",
                return_value="brave-auth-key",
            ) as mock_get_auth_env,
            patch(
                "klaude_code.core.tool.web.web_search_tool._search_brave",
                side_effect=_fake_brave,
            ) as mock_search_brave,
        ):
            args = WebSearchTool.WebSearchArguments(query="prefer env brave key").model_dump_json()
            result = asyncio.run(WebSearchTool.call(args, _tool_context()))

        assert result.status == "success"
        mock_get_auth_env.assert_not_called()
        mock_search_brave.assert_called_once()
        assert mock_search_brave.call_args.args[2] == "brave-env-key"

    def test_uses_exa_auth_env_key_when_brave_missing(self) -> None:
        web_cache.clear()

        def _auth_env_side_effect(name: str) -> str:
            if name == "BRAVE_API_KEY":
                return ""
            if name == "EXA_API_KEY":
                return "exa-auth-key"
            return ""

        with (
            patch(
                "klaude_code.core.tool.web.web_search_tool.get_auth_env",
                side_effect=_auth_env_side_effect,
            ) as mock_get_auth_env,
            patch(
                "klaude_code.core.tool.web.web_search_tool._search_brave",
                side_effect=_fake_brave,
            ) as mock_search_brave,
            patch(
                "klaude_code.core.tool.web.web_search_tool._search_exa",
                side_effect=_fake_exa,
            ) as mock_search_exa,
        ):
            args = WebSearchTool.WebSearchArguments(query="use exa from auth env").model_dump_json()
            result = asyncio.run(WebSearchTool.call(args, _tool_context()))

        assert result.status == "success"
        assert mock_get_auth_env.call_args_list[0].args[0] == "BRAVE_API_KEY"
        assert mock_get_auth_env.call_args_list[1].args[0] == "EXA_API_KEY"
        mock_search_brave.assert_not_called()
        mock_search_exa.assert_called_once()
        assert mock_search_exa.call_args.args[2] == "exa-auth-key"

    def test_uses_exa_env_key_when_brave_missing(self) -> None:
        web_cache.clear()

        with (
            patch.dict(os.environ, {"EXA_API_KEY": "exa-env-key"}),
            patch(
                "klaude_code.core.tool.web.web_search_tool.get_auth_env",
                return_value="",
            ) as mock_get_auth_env,
            patch(
                "klaude_code.core.tool.web.web_search_tool._search_brave",
                side_effect=_fake_brave,
            ) as mock_search_brave,
            patch(
                "klaude_code.core.tool.web.web_search_tool._search_exa",
                side_effect=_fake_exa,
            ) as mock_search_exa,
        ):
            args = WebSearchTool.WebSearchArguments(query="use exa from env").model_dump_json()
            result = asyncio.run(WebSearchTool.call(args, _tool_context()))

        assert result.status == "success"
        mock_get_auth_env.assert_called_once_with("BRAVE_API_KEY")
        mock_search_brave.assert_not_called()
        mock_search_exa.assert_called_once()
        assert mock_search_exa.call_args.args[2] == "exa-env-key"
