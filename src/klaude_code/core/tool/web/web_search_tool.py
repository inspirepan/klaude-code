import asyncio
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel

from klaude_code.core.tool.tool_abc import ToolABC, ToolConcurrencyPolicy, ToolMetadata, load_desc
from klaude_code.core.tool.tool_registry import register
from klaude_code.protocol import llm_param, model, tools

DEFAULT_MAX_RESULTS = 10
MAX_RESULTS_LIMIT = 20


@dataclass
class SearchResult:
    """A single search result from DuckDuckGo."""

    title: str
    url: str
    snippet: str
    position: int


def _search_duckduckgo(query: str, max_results: int) -> list[SearchResult]:
    """Perform a web search using ddgs library."""
    from ddgs import DDGS  # type: ignore

    results: list[SearchResult] = []

    with DDGS() as ddgs:
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


def _format_results(results: list[SearchResult]) -> str:
    """Format search results for LLM consumption."""
    if not results:
        return (
            "No results were found for your search query. "
            "Please try rephrasing your search or using different keywords."
        )

    lines = [f"Found {len(results)} search results:\n"]

    for result in results:
        lines.append(f"{result.position}. {result.title}")
        lines.append(f"   URL: {result.url}")
        lines.append(f"   Summary: {result.snippet}\n")

    return "\n".join(lines)


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
                        "description": f"Maximum number of results to return (default: {DEFAULT_MAX_RESULTS}, max: {MAX_RESULTS_LIMIT})",
                    },
                },
                "required": ["query"],
            },
        )

    class WebSearchArguments(BaseModel):
        query: str
        max_results: int = DEFAULT_MAX_RESULTS

    @classmethod
    async def call(cls, arguments: str) -> model.ToolResultItem:
        try:
            args = WebSearchTool.WebSearchArguments.model_validate_json(arguments)
        except ValueError as e:
            return model.ToolResultItem(
                status="error",
                output=f"Invalid arguments: {e}",
            )
        return await cls.call_with_args(args)

    @classmethod
    async def call_with_args(cls, args: WebSearchArguments) -> model.ToolResultItem:
        query = args.query.strip()
        if not query:
            return model.ToolResultItem(
                status="error",
                output="Query cannot be empty",
            )

        max_results = min(max(args.max_results, 1), MAX_RESULTS_LIMIT)

        try:
            results = await asyncio.to_thread(_search_duckduckgo, query, max_results)
            formatted = _format_results(results)

            return model.ToolResultItem(
                status="success",
                output=formatted,
            )

        except Exception as e:
            return model.ToolResultItem(
                status="error",
                output=f"Search failed: {e}",
            )
