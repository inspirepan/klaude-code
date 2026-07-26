import re

from rich import box
from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.style import Style
from rich.text import Text

from klaude_code.const import SUB_AGENT_RESULT_MAX_LINES
from klaude_code.protocol.models import SubAgentState
from klaude_code.tui.components.common import (
    format_compact_count,
    format_elapsed_compact,
    format_more_lines_indicator,
    format_pascal_case,
)
from klaude_code.tui.components.rich.clip import MaxLines
from klaude_code.tui.components.rich.markdown import NoInsetMarkdown
from klaude_code.tui.components.rich.quote import TreeQuote
from klaude_code.tui.components.rich.theme import ThemeKey

_SUB_AGENT_PROMPT_MAX_LINES = 20
_MARKDOWN_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+")
_MARKDOWN_PREFIX_RE = re.compile(r"^\s*(?:[-*+]\s+|\d+[.)]\s+|>\s*)")
COMPACT_CONTINUATION_PREFIX = "↳ "
# Continuation lines align under the arrow instead of restating it.
COMPACT_CONTINUATION_INDENT = " " * len(COMPACT_CONTINUATION_PREFIX)
# A one-line summary ellipsised mid-sentence says very little; a few wrapped
# lines usually carry the whole conclusion.
COMPACT_RESULT_MAX_LINES = 4


def extract_result_summary(result: str) -> str:
    """Strip Markdown syntax from a result, keeping its line structure.

    Blank lines are dropped, but real line breaks survive: the renderer shows a
    few lines now, so the author's own structure reads better than one run-on line.
    """

    cleaned: list[str] = []
    for raw_line in result.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        text = _MARKDOWN_PREFIX_RE.sub("", _MARKDOWN_HEADING_RE.sub("", line))
        text = re.sub(r"!?(?:\[([^]]+)\])\([^)]+\)", r"\1", text)
        text = re.sub(r"[*_`~]+", "", text)
        text = " ".join(text.split())
        if text:
            cleaned.append(text)
    return "\n".join(cleaned)


def format_compact_result_summary(result_summary: str) -> str:
    """Return a normalized result or an explicit empty-result placeholder."""

    return result_summary or "(no summary)"


def render_compact_sub_agent_summary(
    *,
    title: str,
    description: str,
    status: str,
    model_id: str | None,
    duration_s: float | None,
    tool_count: int,
    token_count: int | None,
    result_summary: str,
    color: Style,
) -> RenderableType:
    """Render a stable two-line compact sub-agent summary."""

    identity_style = Style(color=color.color, bold=True)
    first = Text(no_wrap=True, overflow="ellipsis")
    first.append(title, style=identity_style)
    if description:
        first.append(f": {description}", style=Style(color=color.color, italic=True))
    if status == "success":
        first.append(" ")
        first.append("✓", style=ThemeKey.METADATA_GREEN)
    elif status == "error":
        first.append(" ")
        first.append("✗", style=ThemeKey.ERROR_BOLD)
    else:
        first.append(" cancelled", style=ThemeKey.INTERRUPT)

    metrics: list[str] = []
    if model_id:
        metrics.append(model_id)
    if duration_s is not None:
        metrics.append(format_elapsed_compact(duration_s))
    if tool_count:
        metrics.append(f"{tool_count} {'tool' if tool_count == 1 else 'tools'}")
    if token_count is not None:
        metrics.append(f"{format_compact_count(token_count)} tokens")
    if metrics:
        first.append(f" · {' · '.join(metrics)}", style=ThemeKey.METADATA_DIM)

    return Group(first, render_compact_result_body(result_summary, color=color))


def render_compact_result_body(result_summary: str, *, color: Style) -> RenderableType:
    """Render a sub-agent result as a few wrapped lines hanging off the ↳ marker."""

    # One source line per rendered line: wrapping a long path would spend the
    # whole budget on one value instead of showing several points.
    body = Text(
        format_compact_result_summary(result_summary),
        style=ThemeKey.TOOL_RESULT,
        no_wrap=True,
        overflow="ellipsis",
    )
    return MaxLines(
        TreeQuote(
            body,
            prefix_first=COMPACT_CONTINUATION_PREFIX,
            prefix_middle=COMPACT_CONTINUATION_INDENT,
            prefix_last=COMPACT_CONTINUATION_INDENT,
            style=Style(color=color.color),
            style_first=Style(color=color.color),
        ),
        COMPACT_RESULT_MAX_LINES,
        ellipsis_style=ThemeKey.TOOL_RESULT_TRUNCATED,
    )


def render_compact_file_change(
    *,
    sub_agent_state: SubAgentState,
    action: Text,
    change: RenderableType,
    color: Style,
) -> RenderableType:
    """Render a compact sub-agent identity header followed by a file diff."""

    title = format_pascal_case(sub_agent_state.sub_agent_type)
    header = Text(no_wrap=True, overflow="ellipsis")
    header.append(title, style=Style(color=color.color, bold=True))
    if sub_agent_state.sub_agent_desc:
        header.append(": ", style=Style(color=color.color))
        header.append(sub_agent_state.sub_agent_desc, style=Style(color=color.color, italic=True))
    header.append(" · ", style=ThemeKey.METADATA_DIM)
    header.append_text(action)
    return Group(header, change)


def render_sub_agent_call(
    e: SubAgentState,
    style: Style | None = None,
    *,
    code_theme: str = "monokai",
    effective_model: str | None = None,
) -> RenderableType:
    """Render sub-agent tool call header and prompt body."""
    name_style = Style(color=style.color if style else None, bold=True, reverse=True)
    desc_style = Style(color=style.color if style else None, bgcolor=style.bgcolor if style else None)
    name = Text(f" {format_pascal_case(e.sub_agent_type)} ", style=name_style)
    desc = Text(f" {e.sub_agent_desc} ", style=desc_style)
    header = Text.assemble(name, " ", desc)
    if e.model:
        header.append(f" [model override: {e.model}]", style=ThemeKey.STATUS_HINT)
    elif effective_model:
        header.append(f" [model default: {effective_model}]", style=ThemeKey.STATUS_HINT)
    if e.fork_context:
        header.append(" [fork]", style=ThemeKey.STATUS_HINT)

    prompt_lines = e.sub_agent_prompt.splitlines()
    prompt_source = e.sub_agent_prompt
    hidden_count = 0
    if len(prompt_lines) > _SUB_AGENT_PROMPT_MAX_LINES:
        hidden_count = len(prompt_lines) - _SUB_AGENT_PROMPT_MAX_LINES
        prompt_source = "\n".join(prompt_lines[:_SUB_AGENT_PROMPT_MAX_LINES])

    prompt_content: RenderableType = NoInsetMarkdown(
        prompt_source, code_theme=code_theme, style=Style(color=style.color) if style else ""
    )
    if hidden_count > 0:
        prompt_content = Group(
            prompt_content,
            Text(format_more_lines_indicator(hidden_count), style=ThemeKey.STATUS_HINT),
        )
    elements: list[RenderableType] = [
        header,
        Panel(prompt_content, box=box.ROUNDED, border_style=ThemeKey.LINES),
    ]
    return Group(*elements)


def render_sub_agent_result(
    result: str,
    *,
    description: str | None = None,
    sub_agent_color: Style | None = None,
) -> RenderableType:
    stripped_result = result.strip()

    elements: list[RenderableType] = []
    if description:
        elements.append(
            Text(
                f" {description} ",
                style=Style(bold=True, color=sub_agent_color.color, bgcolor=sub_agent_color.bgcolor)
                if sub_agent_color
                else ThemeKey.TOOL_RESULT_BOLD,
            )
        )

    if not stripped_result:
        return Text()

    lines = stripped_result.splitlines()
    if len(lines) > SUB_AGENT_RESULT_MAX_LINES:
        hidden_count = len(lines) - SUB_AGENT_RESULT_MAX_LINES
        elements.append(Text("\n".join(lines[:SUB_AGENT_RESULT_MAX_LINES]), style=ThemeKey.TOOL_RESULT))
        elements.append(Text(format_more_lines_indicator(hidden_count), style=ThemeKey.TOOL_RESULT_TRUNCATED))
    else:
        elements.append(Text(stripped_result, style=ThemeKey.TOOL_RESULT))

    return Group(*elements)
