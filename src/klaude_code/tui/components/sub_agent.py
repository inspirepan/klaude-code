from rich.console import Group, RenderableType
from rich.style import Style
from rich.text import Text

from klaude_code.const import SUB_AGENT_RESULT_MAX_LINES
from klaude_code.protocol import model
from klaude_code.tui.components.common import format_pascal_case, truncate_head
from klaude_code.tui.components.rich.theme import ThemeKey


def render_sub_agent_call(e: model.SubAgentState, style: Style | None = None) -> RenderableType:
    """Render sub-agent tool call header and prompt body."""
    desc = Text(
        f" {e.sub_agent_desc} ",
        style=Style(color=style.color if style else None, bold=True, reverse=True),
    )
    header = Text.assemble((format_pascal_case(e.sub_agent_type), ThemeKey.TOOL_NAME), " ", desc)
    if e.fork_context:
        header.append(" [fork]", style=ThemeKey.STATUS_HINT)
    elements: list[RenderableType] = [
        header,
        truncate_head(e.sub_agent_prompt, base_style=style or "", truncated_style=ThemeKey.STATUS_HINT, max_lines=10),
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
                f"---\n{description}",
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
        elements.append(Text(f"( ... more {hidden_count} lines)", style=ThemeKey.TOOL_RESULT_TRUNCATED))
    else:
        elements.append(Text(stripped_result, style=ThemeKey.TOOL_RESULT))

    return Group(*elements)
