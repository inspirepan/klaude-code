from rich.console import Group, RenderableType
from rich.style import Style
from rich.text import Text

from klaude_code.const import SUB_AGENT_RESULT_MAX_LINES
from klaude_code.protocol import model
from klaude_code.tui.components.common import format_more_lines_indicator, format_pascal_case
from klaude_code.tui.components.rich.markdown import NoInsetMarkdown
from klaude_code.tui.components.rich.theme import ThemeKey

_SUB_AGENT_PROMPT_MAX_LINES = 20


def render_sub_agent_call(
    e: model.SubAgentState,
    style: Style | None = None,
    *,
    code_theme: str = "monokai",
) -> RenderableType:
    """Render sub-agent tool call header and prompt body."""
    desc = Text(
        f" {e.sub_agent_desc} ",
        style=Style(color=style.color if style else None, bold=True, reverse=True),
    )
    header = Text.assemble((format_pascal_case(e.sub_agent_type), ThemeKey.TOOL_NAME), " ", desc)
    if e.fork_context:
        header.append(" [fork]", style=ThemeKey.STATUS_HINT)

    prompt_lines = e.sub_agent_prompt.splitlines()
    prompt_source = e.sub_agent_prompt
    hidden_count = 0
    if len(prompt_lines) > _SUB_AGENT_PROMPT_MAX_LINES:
        hidden_count = len(prompt_lines) - _SUB_AGENT_PROMPT_MAX_LINES
        prompt_source = "\n".join(prompt_lines[:_SUB_AGENT_PROMPT_MAX_LINES])

    elements: list[RenderableType] = [
        header,
        NoInsetMarkdown(prompt_source, code_theme=code_theme, style=style or ""),
    ]
    if hidden_count > 0:
        elements.append(Text(format_more_lines_indicator(hidden_count), style=ThemeKey.STATUS_HINT))

    elements.append(Text())
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
                description,
                style=Style(bold=True, color=sub_agent_color.color, frame=True)
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
