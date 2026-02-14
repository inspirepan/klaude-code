from __future__ import annotations

import asyncio
import json
import os
import urllib.parse
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from klaude_code.const import WEB_SEARCH_DEFAULT_MAX_RESULTS, WEB_SEARCH_MAX_RESULTS_LIMIT
from klaude_code.core.tool.context import ToolContext
from klaude_code.core.tool.tool_abc import ToolABC, ToolConcurrencyPolicy, ToolMetadata, load_desc
from klaude_code.core.tool.tool_registry import register
from klaude_code.protocol import llm_param, message, tools

_BRAVE_LLM_CONTEXT_URL = "https://api.search.brave.com/res/v1/llm/context"


@contextmanager
def _suppress_native_output() -> Iterator[None]:
    """Suppress stdout/stderr at the OS fd level.

    primp (Rust) prints warnings like "Impersonate 'X' does not exist" directly
    to stderr, bypassing Python's sys.stderr. This corrupts the TUI and causes hangs.
    """
    devnull = os.open(os.devnull, os.O_WRONLY)
    saved_stdout = os.dup(1)
    saved_stderr = os.dup(2)
    try:
        os.dup2(devnull, 1)
        os.dup2(devnull, 2)
        yield
    finally:
        os.dup2(saved_stdout, 1)
        os.dup2(saved_stderr, 2)
        os.close(saved_stdout)
        os.close(saved_stderr)
        os.close(devnull)


@dataclass
class SearchResult:
    """A single search result."""

    title: str
    url: str
    snippet: str
    position: int


def _search_duckduckgo(query: str, max_results: int) -> list[SearchResult]:
    """Perform a web search using ddgs library."""
    from ddgs import DDGS  # type: ignore

    results: list[SearchResult] = []

    with _suppress_native_output(), DDGS() as ddgs:
        for i, r in enumerate(ddgs.text(query, max_results=max_results)):
            results.append(
                SearchResult(
                    title=r.get("title", ""),
                    url=r.get("href", ""),
                    snippet=r.get("body", ""),
                    position=i + 1,
                )
            )

    return results


def _parse_brave_response(raw: bytes) -> list[SearchResult]:
    """Parse Brave LLM Context API response into SearchResult list."""
    data: dict[str, Any] = json.loads(raw)
    grounding: dict[str, Any] = data.get("grounding", {})
    sources: dict[str, Any] = data.get("sources", {})
    items: list[dict[str, Any]] = grounding.get("generic", [])

    results: list[SearchResult] = []
    for i, item in enumerate(items):
        item_url: str = item.get("url", "")
        if not item_url:
            continue
        title: str = item.get("title", "")
        if not title:
            src_meta: dict[str, Any] = sources.get(item_url, {})
            title = src_meta.get("title", "")
        raw_snippets: list[str] = item.get("snippets", [])
        snippet = "\n".join(raw_snippets)
        results.append(SearchResult(title=title, url=item_url, snippet=snippet, position=i + 1))
    return results


def _search_brave(query: str, max_results: int, api_key: str) -> list[SearchResult]:
    """Perform a web search using Brave LLM Context API."""
    params = urllib.parse.urlencode({"q": query, "count": max_results})
    url = f"{_BRAVE_LLM_CONTEXT_URL}?{params}"
    req = urllib.request.Request(url, headers={"Accept": "application/json", "X-Subscription-Token": api_key})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return _parse_brave_response(resp.read())


def _format_results(results: list[SearchResult]) -> str:
    """Format search results for LLM consumption."""
    if not results:
        return (
            "No results were found for your search query. "
            "Please try rephrasing your search or using different keywords."
        )

    parts: list[str] = []
    for result in results:
        parts.append(
            f'<result position="{result.position}">\n'
            f"<title>{result.title}</title>\n"
            f"<url>{result.url}</url>\n"
            f"<snippet>{result.snippet}</snippet>\n"
            f"</result>"
        )

    return "<search_results>\n" + "\n".join(parts) + "\n</search_results>"


@register(tools.WEB_SEARCH)
class WebSearchTool(ToolABC):
    @classmethod
    def metadata(cls) -> ToolMetadata:
        return ToolMetadata(concurrency_policy=ToolConcurrencyPolicy.CONCURRENT, has_side_effects=False)

    @classmethod
    def schema(cls) -> llm_param.ToolSchema:
        return llm_param.ToolSchema(
            name=tools.WEB_SEARCH,
            type="function",
            description=load_desc(Path(__file__).parent / "web_search_tool.md"),
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query to use",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": f"Maximum number of results to return (default: {WEB_SEARCH_DEFAULT_MAX_RESULTS}, max: {WEB_SEARCH_MAX_RESULTS_LIMIT})",
                    },
                },
                "required": ["query"],
            },
        )

    class WebSearchArguments(BaseModel):
        query: str
        max_results: int = WEB_SEARCH_DEFAULT_MAX_RESULTS

    @classmethod
    async def call(cls, arguments: str, context: ToolContext) -> message.ToolResultMessage:
        try:
            args = WebSearchTool.WebSearchArguments.model_validate_json(arguments)
        except ValueError as e:
            return message.ToolResultMessage(
                status="error",
                output_text=f"Invalid arguments: {e}",
            )
        return await cls.call_with_args(args, context)

    @classmethod
    async def call_with_args(cls, args: WebSearchArguments, context: ToolContext) -> message.ToolResultMessage:
        del context
        query = args.query.strip()
        if not query:
            return message.ToolResultMessage(
                status="error",
                output_text="Query cannot be empty",
            )

        max_results = min(max(args.max_results, 1), WEB_SEARCH_MAX_RESULTS_LIMIT)

        try:
            brave_api_key = os.environ.get("BRAVE_API_KEY", "")
            if brave_api_key:
                results = await asyncio.to_thread(_search_brave, query, max_results, brave_api_key)
            else:
                results = await asyncio.to_thread(_search_duckduckgo, query, max_results)
            formatted = _format_results(results)

            return message.ToolResultMessage(
                status="success",
                output_text=formatted,
            )

        except Exception as e:
            return message.ToolResultMessage(
                status="error",
                output_text=f"Search failed: {e}",
            )
