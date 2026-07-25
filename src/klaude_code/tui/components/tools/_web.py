import json
import re
from dataclasses import dataclass
from typing import Any

from rich.console import Group, RenderableType
from rich.table import Table
from rich.text import Text

from klaude_code.const import (
    INVALID_TOOL_CALL_MAX_LENGTH,
    QUERY_DISPLAY_TRUNCATE_LENGTH,
    URL_TRUNCATE_MAX_LENGTH,
    WEB_SEARCH_COMPACT_RESULT_LIMIT,
    WEB_SEARCH_DEFAULT_MAX_RESULTS,
)
from klaude_code.tui.components.rich.theme import ThemeKey
from klaude_code.tui.components.tools._common import (
    MARK_WEB_FETCH,
    MARK_WEB_SEARCH,
    render_tool_call_tree,
)
from klaude_code.tui.transcript_detail import Detail

_EXTERNAL_CONTENT_START = "<<<EXTERNAL_UNTRUSTED_CONTENT>>>"
_EXTERNAL_CONTENT_END = "<<<END_EXTERNAL_UNTRUSTED_CONTENT>>>"
_WEB_FETCH_SAVED_PATH_PREFIX = "[Full content saved to "

_RESULT_BLOCK_PATTERN = re.compile(r"<result\b[^>]*>(.*?)</result>", re.DOTALL)
_TITLE_PATTERN = re.compile(r"<title>(.*?)</title>", re.DOTALL)
_URL_PATTERN = re.compile(r"<url>(.*?)</url>", re.DOTALL)


def _truncate_url(url: str, max_length: int = URL_TRUNCATE_MAX_LENGTH) -> str:
    """Truncate URL for display, preserving domain and path structure."""
    if len(url) <= max_length:
        return url
    # Remove protocol for display
    display_url = url
    for prefix in ("https://", "http://"):
        if display_url.startswith(prefix):
            display_url = display_url[len(prefix) :]
            break
    if len(display_url) <= max_length:
        return display_url
    # Truncate with ellipsis
    return display_url[: max_length - 1] + "\u2026"


def extract_web_result_for_display(result: str) -> str:
    """Extract readable web content from wrapped external-content payloads for TUI display."""
    start_idx = result.find(_EXTERNAL_CONTENT_START)
    end_idx = result.find(_EXTERNAL_CONTENT_END)
    if start_idx == -1 or end_idx == -1 or end_idx < start_idx:
        return result

    prefix = result[:start_idx]
    wrapped_body = result[start_idx + len(_EXTERNAL_CONTENT_START) : end_idx].lstrip("\n")

    lines = wrapped_body.splitlines()
    if len(lines) >= 2 and lines[0].startswith("Source: ") and lines[1].strip() == "---":
        content = "\n".join(lines[2:])
    else:
        divider = "\n---\n"
        divider_idx = wrapped_body.find(divider)
        content = wrapped_body[divider_idx + len(divider) :] if divider_idx != -1 else wrapped_body
    content = content.rstrip("\n")

    prefix_lines = [
        line.strip() for line in prefix.splitlines() if line.strip().startswith(_WEB_FETCH_SAVED_PATH_PREFIX)
    ]
    saved_path_hint = "\n".join(prefix_lines)

    if saved_path_hint and content:
        return f"{saved_path_hint}\n\n{content}"
    if saved_path_hint:
        return saved_path_hint
    return content


@dataclass
class WebSearchResultItem:
    """A single search result extracted from the Web Search tool output."""

    title: str
    url: str


def parse_web_search_results(result: str) -> list[WebSearchResultItem]:
    """Extract title/url pairs from the `<search_results>` payload of a Web Search result."""
    items: list[WebSearchResultItem] = []
    for block in _RESULT_BLOCK_PATTERN.findall(extract_web_result_for_display(result)):
        url_match = _URL_PATTERN.search(block)
        if url_match is None:
            continue
        url = " ".join(url_match.group(1).split())
        if not url:
            continue
        title_match = _TITLE_PATTERN.search(block)
        title = " ".join(title_match.group(1).split()) if title_match else ""
        items.append(WebSearchResultItem(title=title, url=url))
    return items


def render_web_search_results(items: list[WebSearchResultItem], *, detail: Detail) -> RenderableType:
    """Render search results as a numbered list.

    Compact mode lists a few titles only; expanded mode spells out every title
    with its URL on the next line so it can be selected and copied.
    """
    compact = detail.is_compact
    visible = items[:WEB_SEARCH_COMPACT_RESULT_LIMIT] if compact else items

    grid = Table.grid(padding=(0, 1))
    grid.add_column(no_wrap=True, justify="right")
    grid.add_column(overflow="ellipsis" if compact else "fold")

    for index, item in enumerate(visible, start=1):
        number = Text(f"{index}.", ThemeKey.TOOL_RESULT_TRUNCATED)
        # Style the title as a span, not as the Text base style: a base style
        # would also paint the cell padding, stretching the underline to the
        # full terminal width.
        title = Text(no_wrap=compact, overflow="ellipsis" if compact else "fold")
        title.append(item.title or item.url, style=ThemeKey.TOOL_RESULT_LINK)
        grid.add_row(number, title)
        if not compact and item.title:
            url = Text(overflow="fold")
            url.append(item.url, style=ThemeKey.METADATA_DIM)
            grid.add_row(Text(""), url)

    hidden = len(items) - len(visible)
    if hidden <= 0:
        return grid
    return Group(
        grid,
        Text(f"… (more {hidden} results)", ThemeKey.TOOL_RESULT_TRUNCATED, no_wrap=True, overflow="ellipsis"),
    )


def render_web_fetch_tool_call(arguments: str) -> RenderableType:
    tool_name = "Fetch Web"

    try:
        payload: dict[str, str] = json.loads(arguments)
    except json.JSONDecodeError:
        summary = Text(
            arguments.strip()[:INVALID_TOOL_CALL_MAX_LENGTH],
            style=ThemeKey.INVALID_TOOL_CALL_ARGS,
        )
        return render_tool_call_tree(mark=MARK_WEB_FETCH, tool_name=tool_name, details=summary)

    url = payload.get("url", "")
    summary = Text(_truncate_url(url), ThemeKey.TOOL_PARAM_FILE_PATH) if url else Text("(no url)", ThemeKey.TOOL_PARAM)

    return render_tool_call_tree(mark=MARK_WEB_FETCH, tool_name=tool_name, details=summary)


def render_web_search_tool_call(arguments: str) -> RenderableType:
    tool_name = "Search Web"

    try:
        payload: dict[str, Any] = json.loads(arguments)
    except json.JSONDecodeError:
        summary = Text(
            arguments.strip()[:INVALID_TOOL_CALL_MAX_LENGTH],
            style=ThemeKey.INVALID_TOOL_CALL_ARGS,
        )
        return render_tool_call_tree(mark=MARK_WEB_SEARCH, tool_name=tool_name, details=summary)

    query = payload.get("query", "")
    max_results = payload.get("max_results")

    summary = Text("", ThemeKey.TOOL_PARAM)
    if query:
        # Truncate long queries
        display_query = (
            query
            if len(query) <= QUERY_DISPLAY_TRUNCATE_LENGTH
            else query[: QUERY_DISPLAY_TRUNCATE_LENGTH - 1] + "\u2026"
        )
        summary.append(display_query, ThemeKey.TOOL_PARAM)
    else:
        summary.append("(no query)", ThemeKey.TOOL_PARAM)

    if isinstance(max_results, int) and max_results != WEB_SEARCH_DEFAULT_MAX_RESULTS:
        summary.append(f" (max {max_results})", ThemeKey.TOOL_TIMEOUT)

    return render_tool_call_tree(mark=MARK_WEB_SEARCH, tool_name=tool_name, details=summary)
