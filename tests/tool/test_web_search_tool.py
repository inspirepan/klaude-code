from __future__ import annotations

import asyncio
import os
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest

from klaude_code.config.config import Config, WebSearchConfig, WebSearchProviderConfig
from klaude_code.protocol import message
from klaude_code.protocol.models import WebSearchUIExtra
from klaude_code.tool import WebSearchTool
from klaude_code.tool.core.context import TodoContext, ToolContext
from klaude_code.tool.web.external_content import (
    _BOUNDARY_END,  # pyright: ignore[reportPrivateUsage]
    _BOUNDARY_START,  # pyright: ignore[reportPrivateUsage]
)
from klaude_code.tool.web.web_cache import _cache as web_cache  # pyright: ignore[reportPrivateUsage]
from klaude_code.tool.web.web_search_tool import SearchOutcome, SearchProviderError, SearchResult


def _tool_context() -> ToolContext:
    todo_context = TodoContext(get_todos=lambda: [], set_todos=lambda todos: None)
    return ToolContext(file_tracker={}, todo_context=todo_context, session_id="test", work_dir=Path("/tmp"))


def _config_with(*providers: WebSearchProviderConfig) -> Config:
    return Config(web_search=WebSearchConfig(providers=list(providers)))


def _exa_brave_config() -> Config:
    return _config_with(
        WebSearchProviderConfig(provider="exa", api_key="${EXA_API_KEY}"),
        WebSearchProviderConfig(provider="brave", api_key="${BRAVE_API_KEY}"),
    )


@pytest.fixture(autouse=True)
def _clean_search_env(isolated_home: Path) -> Iterator[None]:  # pyright: ignore[reportUnusedFunction]
    del isolated_home  # fixture only needed for its side effects
    web_cache.clear()
    with (
        patch.dict(
            os.environ,
            {
                "PARALLEL_API_KEY": "",
                "EXA_API_KEY": "",
                "BRAVE_API_KEY": "",
                "DEEPSEEK_API_KEY": "",
                "OPENAI_API_KEY": "",
            },
        ),
        patch("klaude_code.config.config.get_auth_env", return_value=None),
    ):
        yield


def _fake_search(_query: str, _max_results: int, _api_key: str) -> SearchOutcome:
    return SearchOutcome(
        results=[
            SearchResult(title="Result 1", url="https://example.com/1", snippet="First result", position=1),
            SearchResult(title="Result 2", url="https://example.com/2", snippet="Second result", position=2),
        ]
    )


def _run(config: Config, query: str = "test query") -> message.ToolResultMessage:
    with patch("klaude_code.tool.web.web_search_tool.load_config", return_value=config):
        args = WebSearchTool.WebSearchArguments(query=query).model_dump_json()
        return asyncio.run(WebSearchTool.call(args, _tool_context()))


class TestWebSearchSecurity:
    def test_results_wrapped_with_boundary(self) -> None:
        with (
            patch.dict(os.environ, {"EXA_API_KEY": "exa-key"}),
            patch("klaude_code.tool.web.web_search_tool._search_exa", side_effect=_fake_search),
        ):
            result = _run(_exa_brave_config())
        assert result.status == "success"
        assert result.output_text is not None
        assert _BOUNDARY_START in result.output_text
        assert _BOUNDARY_END in result.output_text

    def test_no_security_warning(self) -> None:
        """Web search results should NOT include the security warning (only boundary markers)."""
        with (
            patch.dict(os.environ, {"EXA_API_KEY": "exa-key"}),
            patch("klaude_code.tool.web.web_search_tool._search_exa", side_effect=_fake_search),
        ):
            result = _run(_exa_brave_config(), "another query")
        assert result.status == "success"
        assert result.output_text is not None
        assert "SECURITY NOTICE" not in result.output_text

    def test_search_results_in_output(self) -> None:
        with (
            patch.dict(os.environ, {"EXA_API_KEY": "exa-key"}),
            patch("klaude_code.tool.web.web_search_tool._search_exa", side_effect=_fake_search),
        ):
            result = _run(_exa_brave_config(), "find results")
        assert result.status == "success"
        assert result.output_text is not None
        assert "<search_results>" in result.output_text
        assert "Result 1" in result.output_text


class TestWebSearchCaching:
    def test_cache_hit(self) -> None:
        call_count = 0

        def counting_search(query: str, max_results: int, _api_key: str) -> SearchOutcome:
            nonlocal call_count
            call_count += 1
            return _fake_search(query, max_results, _api_key)

        with (
            patch.dict(os.environ, {"EXA_API_KEY": "exa-key"}),
            patch("klaude_code.tool.web.web_search_tool._search_exa", side_effect=counting_search),
        ):
            r1 = _run(_exa_brave_config(), "cached search")
            r2 = _run(_exa_brave_config(), "cached search")
        assert r1.status == "success"
        assert r2.status == "success"
        assert r1.ui_extra == r2.ui_extra == WebSearchUIExtra(provider="exa")
        assert r1.output_text == r2.output_text
        assert call_count == 1

    def test_different_queries_not_cached(self) -> None:
        call_count = 0

        def counting_search(query: str, max_results: int, _api_key: str) -> SearchOutcome:
            nonlocal call_count
            call_count += 1
            return _fake_search(query, max_results, _api_key)

        with (
            patch.dict(os.environ, {"EXA_API_KEY": "exa-key"}),
            patch("klaude_code.tool.web.web_search_tool._search_exa", side_effect=counting_search),
        ):
            _run(_exa_brave_config(), "query one")
            _run(_exa_brave_config(), "query two")
        assert call_count == 2


class TestProviderChainResolution:
    def test_returns_error_when_no_provider_has_a_key(self) -> None:
        result = _run(_exa_brave_config(), "missing key")
        assert result.status == "error"
        assert result.ui_extra is None
        assert result.output_text is not None
        assert "PARALLEL_API_KEY" in result.output_text
        assert "EXA_API_KEY" in result.output_text
        assert "BRAVE_API_KEY" in result.output_text
        assert "DEEPSEEK_API_KEY" in result.output_text
        assert "OPENAI_API_KEY" in result.output_text

    def test_auth_env_key_used_when_process_env_missing(self) -> None:
        def _auth_env(name: str) -> str | None:
            return "exa-auth-key" if name == "EXA_API_KEY" else None

        with (
            patch("klaude_code.config.config.get_auth_env", side_effect=_auth_env),
            patch("klaude_code.tool.web.web_search_tool._search_exa", side_effect=_fake_search) as mock_search_exa,
        ):
            result = _run(_exa_brave_config(), "use exa from auth env")

        assert result.status == "success"
        mock_search_exa.assert_called_once()
        assert mock_search_exa.call_args.args[2] == "exa-auth-key"

    def test_process_env_key_takes_precedence_over_auth_env(self) -> None:
        with (
            patch.dict(os.environ, {"EXA_API_KEY": "exa-env-key"}),
            patch("klaude_code.config.config.get_auth_env", return_value="auth-key"),
            patch("klaude_code.tool.web.web_search_tool._search_exa", side_effect=_fake_search) as mock_search_exa,
        ):
            result = _run(_exa_brave_config(), "prefer env exa key")

        assert result.status == "success"
        mock_search_exa.assert_called_once()
        assert mock_search_exa.call_args.args[2] == "exa-env-key"

    def test_parallel_precedes_exa_by_config_order(self) -> None:
        config = _config_with(
            WebSearchProviderConfig(provider="parallel", api_key="${PARALLEL_API_KEY}"),
            WebSearchProviderConfig(provider="exa", api_key="${EXA_API_KEY}"),
        )
        with (
            patch.dict(os.environ, {"PARALLEL_API_KEY": "parallel-key", "EXA_API_KEY": "exa-key"}),
            patch("klaude_code.tool.web.web_search_tool._search_parallel", side_effect=_fake_search) as mock_parallel,
            patch("klaude_code.tool.web.web_search_tool._search_exa", side_effect=_fake_search) as mock_exa,
        ):
            result = _run(config, "parallel first by config order")

        assert result.status == "success"
        mock_parallel.assert_called_once()
        assert mock_parallel.call_args.args[2] == "parallel-key"
        mock_exa.assert_not_called()

    def test_config_order_defines_priority(self) -> None:
        config = _config_with(
            WebSearchProviderConfig(provider="brave", api_key="${BRAVE_API_KEY}"),
            WebSearchProviderConfig(provider="exa", api_key="${EXA_API_KEY}"),
        )
        with (
            patch.dict(os.environ, {"EXA_API_KEY": "exa-key", "BRAVE_API_KEY": "brave-key"}),
            patch("klaude_code.tool.web.web_search_tool._search_brave", side_effect=_fake_search) as mock_brave,
            patch("klaude_code.tool.web.web_search_tool._search_exa", side_effect=_fake_search) as mock_exa,
        ):
            result = _run(config, "brave first by config order")

        assert result.status == "success"
        mock_brave.assert_called_once()
        mock_exa.assert_not_called()

    def test_deepseek_search_needs_no_model_when_only_its_key_exists(self) -> None:
        config = _config_with(
            WebSearchProviderConfig(provider="exa", api_key="${EXA_API_KEY}"),
            WebSearchProviderConfig(
                provider="deepseek",
                api_key="${DEEPSEEK_API_KEY}",
            ),
        )

        def _fake_deepseek(query: str, max_results: int, api_key: str, base_url: str | None) -> SearchOutcome:
            assert api_key == "ds-key"
            assert base_url is None
            return SearchOutcome(
                results=[SearchResult(title="DS", url="https://example.com/ds", snippet="s", position=1)],
            )

        with (
            patch.dict(os.environ, {"DEEPSEEK_API_KEY": "ds-key"}),
            patch("klaude_code.tool.web.web_search_tool._search_deepseek", side_effect=_fake_deepseek),
        ):
            result = _run(config, "deepseek path")

        assert result.status == "success"
        assert result.output_text is not None
        assert "<answer>" not in result.output_text
        assert "https://example.com/ds" in result.output_text
        assert result.ui_extra == WebSearchUIExtra(provider="deepseek")


class TestProviderFailureFallback:
    def test_deepseek_empty_results_do_not_trigger_fallback(self) -> None:
        config = _config_with(
            WebSearchProviderConfig(provider="deepseek", api_key="ds-key"),
            WebSearchProviderConfig(provider="brave", api_key="brave-key"),
        )
        with (
            patch("klaude_code.tool.web.web_search_tool._fetch_json", return_value={"results": []}) as fetch,
            patch("klaude_code.tool.web.web_search_tool._search_brave") as brave,
        ):
            result = _run(config)
            cached_result = _run(config)
        assert result.status == "success"
        assert cached_result.status == "success"
        assert result.ui_extra == cached_result.ui_extra == WebSearchUIExtra(provider="deepseek")
        assert result.output_text == cached_result.output_text
        assert result.output_text is not None
        assert "No results were found" in result.output_text
        fetch.assert_called_once()
        brave.assert_not_called()

    def test_deepseek_long_query_falls_back_without_truncation(self) -> None:
        config = _config_with(
            WebSearchProviderConfig(provider="deepseek", api_key="ds-key"),
            WebSearchProviderConfig(provider="brave", api_key="brave-key"),
        )
        query = "x" * 129
        with (
            patch("klaude_code.tool.web.web_search_tool._fetch_json") as fetch,
            patch("klaude_code.tool.web.web_search_tool._search_brave", side_effect=_fake_search) as brave,
        ):
            result = _run(config, query)
        assert result.status == "success"
        fetch.assert_not_called()
        brave.assert_called_once_with(query, 10, "brave-key")

    def test_falls_back_to_next_provider_when_request_fails(self) -> None:
        def _failing_exa(_query: str, _max_results: int, _api_key: str) -> SearchOutcome:
            raise ConnectionError("exa unreachable")

        with (
            patch.dict(os.environ, {"EXA_API_KEY": "exa-key", "BRAVE_API_KEY": "brave-key"}),
            patch("klaude_code.tool.web.web_search_tool._search_exa", side_effect=_failing_exa) as mock_exa,
            patch("klaude_code.tool.web.web_search_tool._search_brave", side_effect=_fake_search) as mock_brave,
        ):
            result = _run(_exa_brave_config(), "exa down, brave up")
            cached_result = _run(_exa_brave_config(), "exa down, brave up")

        assert result.status == "success"
        assert cached_result.status == "success"
        assert result.ui_extra == cached_result.ui_extra == WebSearchUIExtra(provider="brave")
        assert result.output_text == cached_result.output_text
        assert mock_exa.call_count == 2
        mock_brave.assert_called_once()
        assert result.output_text is not None
        assert "Result 1" in result.output_text

    def test_deepseek_api_error_falls_back(self) -> None:
        def _failing_deepseek(_q: str, _m: int, _k: str, _b: str | None) -> SearchOutcome:
            raise SearchProviderError("HTTP 429: rate limit exceeded")

        config = _config_with(
            WebSearchProviderConfig(
                provider="deepseek",
                api_key="${DEEPSEEK_API_KEY}",
            ),
            WebSearchProviderConfig(provider="brave", api_key="${BRAVE_API_KEY}"),
        )
        with (
            patch.dict(os.environ, {"DEEPSEEK_API_KEY": "ds-key", "BRAVE_API_KEY": "brave-key"}),
            patch("klaude_code.tool.web.web_search_tool._search_deepseek", side_effect=_failing_deepseek),
            patch("klaude_code.tool.web.web_search_tool._search_brave", side_effect=_fake_search) as mock_brave,
        ):
            result = _run(config, "deepseek rate limited, brave up")

        assert result.status == "success"
        mock_brave.assert_called_once()

    def test_error_when_all_providers_fail(self) -> None:
        def _failing_exa(_query: str, _max_results: int, _api_key: str) -> SearchOutcome:
            raise ConnectionError("exa unreachable")

        def _failing_brave(_query: str, _max_results: int, _api_key: str) -> SearchOutcome:
            raise TimeoutError("brave timed out")

        with (
            patch.dict(os.environ, {"EXA_API_KEY": "exa-key", "BRAVE_API_KEY": "brave-key"}),
            patch("klaude_code.tool.web.web_search_tool._search_exa", side_effect=_failing_exa),
            patch("klaude_code.tool.web.web_search_tool._search_brave", side_effect=_failing_brave),
        ):
            result = _run(_exa_brave_config(), "both providers down")

        assert result.status == "error"
        assert result.ui_extra is None
        assert result.output_text is not None
        assert "exa: exa unreachable" in result.output_text
        assert "brave: brave timed out" in result.output_text

    def test_error_when_exa_fails_and_no_brave_key(self) -> None:
        def _failing_exa(_query: str, _max_results: int, _api_key: str) -> SearchOutcome:
            raise ConnectionError("exa unreachable")

        with (
            patch.dict(os.environ, {"EXA_API_KEY": "exa-key"}),
            patch("klaude_code.tool.web.web_search_tool._search_exa", side_effect=_failing_exa),
        ):
            result = _run(_exa_brave_config(), "exa down, no brave key")

        assert result.status == "error"
        assert result.output_text is not None
        assert "exa: exa unreachable" in result.output_text
