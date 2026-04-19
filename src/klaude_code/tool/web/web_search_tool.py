from __future__ import annotations

import asyncio
import json
import os
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from klaude_code.auth.env import get_auth_env
from klaude_code.const import WEB_SEARCH_DEFAULT_MAX_RESULTS, WEB_SEARCH_MAX_RESULTS_LIMIT
from klaude_code.protocol import llm_param, message, tools
from klaude_code.tool.core.abc import ToolABC, ToolConcurrencyPolicy, ToolMetadata, load_desc
from klaude_code.tool.core.context import ToolContext
from klaude_code.tool.core.registry import register
from klaude_code.tool.web.external_content import wrap_web_content
from klaude_code.tool.web.web_cache import get_cached, make_cache_key, set_cached

_BRAVE_LLM_CONTEXT_URL = "https://api.search.brave.com/res/v1/llm/context"
_EXA_SEARCH_URL = "https://api.exa.ai/search"


@dataclass
class SearchResult:
    """A single search result."""

    title: str
    url: str
    snippet: str
    position: int


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


def _parse_exa_response(raw: bytes) -> list[SearchResult]:
    """Parse Exa search response into SearchResult list."""
    data: dict[str, Any] = json.loads(raw)
    items: list[dict[str, Any]] = data.get("results", [])

    results: list[SearchResult] = []
    for i, item in enumerate(items):
        item_url: str = item.get("url", "")
        if not item_url:
            continue

        title: str = item.get("title", "")
        highlights: list[Any] = item.get("highlights", [])
        highlight_texts = [h for h in highlights if isinstance(h, str)]
        snippet = "\n".join(highlight_texts)
        if not snippet:
            snippet = item.get("summary", "")

        results.append(SearchResult(title=title, url=item_url, snippet=snippet, position=i + 1))

    return results


def _search_exa(query: str, max_results: int, api_key: str) -> list[SearchResult]:
    """Perform a web search using Exa Search API."""
    payload = {
        "query": query,
        "type": "auto",
        "numResults": max_results,
        "contents": {"highlights": {"maxCharacters": 4000}},
    }
    req = urllib.request.Request(
        _EXA_SEARCH_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "User-Agent": "klaude-code/2",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return _parse_exa_response(resp.read())


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
            exa_api_key = os.environ.get("EXA_API_KEY") or get_auth_env("EXA_API_KEY") or ""
            provider = "exa"
            provider_api_key = exa_api_key

            if not provider_api_key:
                brave_api_key = os.environ.get("BRAVE_API_KEY") or get_auth_env("BRAVE_API_KEY") or ""
                provider = "brave"
                provider_api_key = brave_api_key

            if not provider_api_key:
                return message.ToolResultMessage(
                    status="error",
                    output_text="Search failed: missing EXA_API_KEY or BRAVE_API_KEY. Please set one and try again.",
                )

            # Check cache
            cache_key = make_cache_key("search", provider, query, str(max_results))
            cached = get_cached(cache_key)
            if cached is not None:
                return message.ToolResultMessage(status="success", output_text=cached)

            if provider == "brave":
                results = await asyncio.to_thread(_search_brave, query, max_results, provider_api_key)
            else:
                results = await asyncio.to_thread(_search_exa, query, max_results, provider_api_key)

            formatted = _format_results(results)
            wrapped = wrap_web_content(formatted, source="Web Search", include_warning=False)

            set_cached(cache_key, wrapped)
            return message.ToolResultMessage(
                status="success",
                output_text=wrapped,
            )

        except Exception as e:
            return message.ToolResultMessage(
                status="error",
                output_text=f"Search failed: {e}",
            )
