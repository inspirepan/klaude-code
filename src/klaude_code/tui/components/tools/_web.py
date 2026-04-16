import json
from typing import Any

from rich.console import RenderableType
from rich.text import Text

from klaude_code.const import (
    INVALID_TOOL_CALL_MAX_LENGTH,
    QUERY_DISPLAY_TRUNCATE_LENGTH,
    URL_TRUNCATE_MAX_LENGTH,
    WEB_SEARCH_DEFAULT_MAX_RESULTS,
)
from klaude_code.tui.components.rich.theme import ThemeKey
from klaude_code.tui.components.tools._common import (
    MARK_WEB_FETCH,
    MARK_WEB_SEARCH,
    render_tool_call_tree,
)

_EXTERNAL_CONTENT_START = "<<<EXTERNAL_UNTRUSTED_CONTENT>>>"
_EXTERNAL_CONTENT_END = "<<<END_EXTERNAL_UNTRUSTED_CONTENT>>>"
_WEB_FETCH_SAVED_PATH_PREFIX = "[Full content saved to "


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
