from __future__ import annotations

import asyncio
import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from klaude_code.config.config import WebSearchProviderName, resolve_api_key
from klaude_code.config.loader import load_config
from klaude_code.const import (
    WEB_SEARCH_DEEPSEEK_API_VERSION,
    WEB_SEARCH_DEEPSEEK_MAX_TOKENS,
    WEB_SEARCH_DEEPSEEK_MAX_USES,
    WEB_SEARCH_DEFAULT_MAX_RESULTS,
    WEB_SEARCH_LLM_TIMEOUT_SEC,
    WEB_SEARCH_MAX_RESULTS_LIMIT,
    WEB_SEARCH_SNIPPET_MAX_CHARS,
)
from klaude_code.protocol import llm_param, message, tools
from klaude_code.tool.core.abc import ToolABC, ToolConcurrencyPolicy, ToolMetadata, load_desc
from klaude_code.tool.core.context import ToolContext
from klaude_code.tool.core.registry import register
from klaude_code.tool.web.external_content import wrap_web_content
from klaude_code.tool.web.web_cache import get_cached, make_cache_key, set_cached

_BRAVE_LLM_CONTEXT_URL = "https://api.search.brave.com/res/v1/llm/context"
_EXA_SEARCH_URL = "https://api.exa.ai/search"
_SEARCH_API_TIMEOUT_SEC = 30


class SearchProviderError(Exception):
    """One search provider failed; the chain falls back to the next provider."""


@dataclass
class SearchResult:
    """A single search result."""

    title: str
    url: str
    snippet: str
    position: int
    published: str | None = None


@dataclass
class SearchOutcome:
    """One provider's search output: citeable sources plus an optional generated answer."""

    results: list[SearchResult]
    answer: str | None = None


@dataclass
class _ResolvedProvider:
    """A chain entry with its credential resolved, ready to dispatch."""

    name: WebSearchProviderName
    api_key: str
    base_url: str | None
    model: str | None


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Refuse redirects so API-key headers are never forwarded to another origin."""

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        return None


_opener = urllib.request.build_opener(_NoRedirectHandler)


def _fetch_json(req: urllib.request.Request, timeout: int) -> dict[str, Any]:
    """POST/GET a JSON request and parse the response body; redirects and HTTP errors raise."""
    try:
        with _opener.open(req, timeout=timeout) as resp:
            raw: bytes = resp.read()
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            body: dict[str, Any] = json.loads(e.read())
            error_field: Any = body.get("error")
            if isinstance(error_field, dict):
                detail = str(error_field.get("message") or "")
            elif error_field is not None:
                detail = str(error_field)
            if not detail:
                detail = str(body.get("message") or "")
        except (json.JSONDecodeError, OSError, UnicodeDecodeError):
            detail = ""
        message = f"HTTP {e.code}" + (f": {detail}" if detail else "")
        raise SearchProviderError(message) from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise SearchProviderError(str(e)) from e
    data: dict[str, Any] = json.loads(raw)
    return data


# ---------------------------------------------------------------------------
# Brave / Exa: dedicated search APIs
# ---------------------------------------------------------------------------


def _parse_brave_response(data: dict[str, Any]) -> list[SearchResult]:
    """Parse Brave LLM Context API response into SearchResult list."""
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


def _search_brave(query: str, max_results: int, api_key: str) -> SearchOutcome:
    """Perform a web search using Brave LLM Context API."""
    params = urllib.parse.urlencode({"q": query, "count": max_results})
    url = f"{_BRAVE_LLM_CONTEXT_URL}?{params}"
    req = urllib.request.Request(url, headers={"Accept": "application/json", "X-Subscription-Token": api_key})
    data = _fetch_json(req, _SEARCH_API_TIMEOUT_SEC)
    return SearchOutcome(results=_parse_brave_response(data))


def _parse_exa_response(data: dict[str, Any]) -> list[SearchResult]:
    """Parse Exa search response into SearchResult list."""
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


def _search_exa(query: str, max_results: int, api_key: str) -> SearchOutcome:
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
    data = _fetch_json(req, _SEARCH_API_TIMEOUT_SEC)
    return SearchOutcome(results=_parse_exa_response(data))


# ---------------------------------------------------------------------------
# DeepSeek / OpenAI: LLM-backed search (one search = one model turn)
# ---------------------------------------------------------------------------


def _cap_snippet(text: str) -> str:
    if len(text) <= WEB_SEARCH_SNIPPET_MAX_CHARS:
        return text
    return text[: WEB_SEARCH_SNIPPET_MAX_CHARS - 1] + "…"


def _parse_deepseek_response(data: dict[str, Any], max_results: int) -> SearchOutcome:
    """Map a DeepSeek Anthropic Messages response to a SearchOutcome.

    Citeable items arrive in ``web_search_tool_result`` blocks (url/title/page_age);
    the excerpt lives in separate ``text`` blocks' ``citations[]``, joined by URL.
    Absence of structured sources is an error, never a prose-scraping fallback.
    """
    blocks: list[dict[str, Any]] = data.get("content") or []

    answer_parts: list[str] = []
    snippets: dict[str, str] = {}
    for block in blocks:
        if block.get("type") != "text":
            continue
        text: str = block.get("text") or ""
        if text:
            answer_parts.append(text)
        for cite in block.get("citations") or []:
            cite_url: str = cite.get("url") or ""
            cited_text: str = cite.get("cited_text") or ""
            if cite_url and cited_text and cite_url not in snippets:
                snippets[cite_url] = cited_text

    results: list[SearchResult] = []
    seen: set[str] = set()
    for block in blocks:
        if block.get("type") != "web_search_tool_result":
            continue
        for item in block.get("content") or []:
            if item.get("type") != "web_search_result":
                continue
            item_url: str = item.get("url") or ""
            if not item_url or item_url in seen:
                continue
            seen.add(item_url)
            results.append(
                SearchResult(
                    title=item.get("title") or "",
                    url=item_url,
                    snippet=_cap_snippet(snippets.get(item_url, "")),
                    published=item.get("page_age") or None,
                    position=len(results) + 1,
                )
            )

    results = results[:max_results]
    for i, result in enumerate(results):
        result.position = i + 1
    if not results:
        raise SearchProviderError("native web search returned no result blocks")
    return SearchOutcome(results=results, answer="\n\n".join(answer_parts) or None)


def _search_deepseek(query: str, max_results: int, api_key: str, base_url: str, model: str) -> SearchOutcome:
    """Search via DeepSeek's Anthropic-compatible Messages API with native web_search."""
    endpoint = f"{base_url.rstrip('/')}/v1/messages"
    body = {
        "model": model,
        "max_tokens": WEB_SEARCH_DEEPSEEK_MAX_TOKENS,
        "messages": [
            {"role": "user", "content": [{"type": "text", "text": f"Perform a web search for the query: {query}"}]}
        ],
        "tools": [{"type": "web_search_20250305", "name": "web_search", "max_uses": WEB_SEARCH_DEEPSEEK_MAX_USES}],
    }
    req = urllib.request.Request(
        endpoint,
        data=json.dumps(body).encode("utf-8"),
        headers={
            # Official DeepSeek expects x-api-key; an Anthropic-compatible proxy
            # may expect Authorization: Bearer — send both so either resolves.
            "x-api-key": api_key,
            "authorization": f"Bearer {api_key}",
            "anthropic-version": WEB_SEARCH_DEEPSEEK_API_VERSION,
            "content-type": "application/json",
            "accept": "application/json",
        },
    )
    data = _fetch_json(req, WEB_SEARCH_LLM_TIMEOUT_SEC)
    return _parse_deepseek_response(data, max_results)


def _parse_openai_response(data: dict[str, Any], max_results: int) -> SearchOutcome:
    """Map an OpenAI Responses API response to a SearchOutcome.

    Sources come from ``url_citation`` annotations on the assistant message's
    ``output_text`` parts; the snippet is the cited span of the answer text.
    Absence of citations means the model chose not to search — an error here.
    """
    output_items: list[dict[str, Any]] = data.get("output") or []

    answer_parts: list[str] = []
    results: list[SearchResult] = []
    seen: set[str] = set()
    for item in output_items:
        if item.get("type") != "message":
            continue
        for part in item.get("content") or []:
            if part.get("type") != "output_text":
                continue
            text: str = part.get("text") or ""
            if text:
                answer_parts.append(text)
            for ann in part.get("annotations") or []:
                if ann.get("type") != "url_citation":
                    continue
                ann_url: str = ann.get("url") or ""
                if not ann_url or ann_url in seen:
                    continue
                seen.add(ann_url)
                snippet = ""
                start, end = ann.get("start_index"), ann.get("end_index")
                if isinstance(start, int) and isinstance(end, int) and 0 <= start <= end <= len(text):
                    snippet = text[start:end]
                results.append(
                    SearchResult(
                        title=ann.get("title") or "",
                        url=ann_url,
                        snippet=_cap_snippet(snippet),
                        position=len(results) + 1,
                    )
                )

    results = results[:max_results]
    for i, result in enumerate(results):
        result.position = i + 1
    if not results:
        raise SearchProviderError("model returned no URL citations (it may not have searched)")
    return SearchOutcome(results=results, answer="\n\n".join(answer_parts) or None)


def _search_openai(query: str, max_results: int, api_key: str, base_url: str, model: str) -> SearchOutcome:
    """Search via the OpenAI Responses API with the hosted web_search tool."""
    endpoint = f"{base_url.rstrip('/')}/responses"
    body = {
        "model": model,
        "tools": [{"type": "web_search"}],
        "input": f"Perform a web search for the query: {query}",
    }
    req = urllib.request.Request(
        endpoint,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "authorization": f"Bearer {api_key}",
            "content-type": "application/json",
            "accept": "application/json",
        },
    )
    data = _fetch_json(req, WEB_SEARCH_LLM_TIMEOUT_SEC)
    return _parse_openai_response(data, max_results)


# ---------------------------------------------------------------------------
# Provider chain
# ---------------------------------------------------------------------------


def _resolve_provider_chain() -> list[_ResolvedProvider]:
    """Build the provider chain from config, skipping entries whose API key is missing."""
    config = load_config()
    chain: list[_ResolvedProvider] = []
    for entry in config.web_search.providers:
        api_key = resolve_api_key(entry.api_key)
        if not api_key:
            continue
        chain.append(
            _ResolvedProvider(name=entry.provider, api_key=api_key, base_url=entry.base_url, model=entry.model)
        )
    return chain


def _run_provider(provider: _ResolvedProvider, query: str, max_results: int) -> SearchOutcome:
    if provider.name == "exa":
        return _search_exa(query, max_results, provider.api_key)
    if provider.name == "brave":
        return _search_brave(query, max_results, provider.api_key)
    if provider.base_url is None or provider.model is None:
        raise SearchProviderError(f"{provider.name} provider requires base_url and model in web_search config")
    if provider.name == "deepseek":
        return _search_deepseek(query, max_results, provider.api_key, provider.base_url, provider.model)
    return _search_openai(query, max_results, provider.api_key, provider.base_url, provider.model)


def _format_results(results: list[SearchResult], answer: str | None = None) -> str:
    """Format search results for LLM consumption."""
    answer_block = f"<answer>\n{answer}\n</answer>\n" if answer else ""
    if not results:
        return answer_block + (
            "No results were found for your search query. "
            "Please try rephrasing your search or using different keywords."
        )

    parts: list[str] = []
    for result in results:
        title = result.title or urllib.parse.urlparse(result.url).netloc
        lines = [
            f'<result position="{result.position}">',
            f"<title>{title}</title>",
            f"<url>{result.url}</url>",
        ]
        if result.snippet:
            lines.append(f"<snippet>{result.snippet}</snippet>")
        if result.published:
            lines.append(f"<published>{result.published}</published>")
        lines.append("</result>")
        parts.append("\n".join(lines))

    return answer_block + "<search_results>\n" + "\n".join(parts) + "\n</search_results>"


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

        # Provider chain comes from config (order = priority); on failure, fall
        # back to the next provider. Entries without a resolvable key are skipped.
        try:
            providers = _resolve_provider_chain()
        except (OSError, ValueError) as e:
            return message.ToolResultMessage(status="error", output_text=f"Search failed: cannot load config: {e}")

        if not providers:
            return message.ToolResultMessage(
                status="error",
                output_text=(
                    "Search failed: no web search provider has an API key. Set EXA_API_KEY, BRAVE_API_KEY, "
                    "DEEPSEEK_API_KEY, or OPENAI_API_KEY (or configure `web_search` in klaude-config.yaml)."
                ),
            )

        errors: list[str] = []
        for provider in providers:
            cache_key = make_cache_key("search", provider.name, query, str(max_results))
            cached = get_cached(cache_key)
            if cached is not None:
                return message.ToolResultMessage(status="success", output_text=cached)

            try:
                outcome = await asyncio.to_thread(_run_provider, provider, query, max_results)
            except Exception as e:
                errors.append(f"{provider.name}: {e}")
                continue

            formatted = _format_results(outcome.results, outcome.answer)
            wrapped = wrap_web_content(formatted, source="Web Search", include_warning=False)

            set_cached(cache_key, wrapped)
            return message.ToolResultMessage(
                status="success",
                output_text=wrapped,
            )

        return message.ToolResultMessage(
            status="error",
            output_text=f"Search failed: {'; '.join(errors)}",
        )
