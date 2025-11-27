from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.style import Style
from rich.text import Text

from klaude_code.config.constants import SUB_AGENT_RESULT_MAX_LINES
from klaude_code.protocol import model
from klaude_code.ui.base.theme import ThemeKey
from klaude_code.ui.rich_ext.markdown import NoInsetMarkdown


def render_sub_agent_call(e: model.SubAgentState, style: Style | None = None) -> RenderableType:
    """Render sub-agent tool call header and prompt body."""
    desc = Text(
        f" {e.sub_agent_desc} ",
        style=Style(color=style.color if style else None, bold=True, reverse=True),
    )
    return Group(
        Text.assemble((e.sub_agent_type, ThemeKey.TOOL_NAME), " ", desc),
        Text(e.sub_agent_prompt, style=style or ""),
    )


def render_sub_agent_result(result: str, *, code_theme: str, style: Style | None = None) -> RenderableType:
    stripped_result = result.strip()
    lines = stripped_result.splitlines()
    if len(lines) > SUB_AGENT_RESULT_MAX_LINES:
        hidden_count = len(lines) - SUB_AGENT_RESULT_MAX_LINES
        truncated_text = "\n".join(lines[-SUB_AGENT_RESULT_MAX_LINES:])
        return Panel.fit(
            Group(
                Text(f"... more {hidden_count} lines — use /export to view full output", style=ThemeKey.TOOL_RESULT),
                NoInsetMarkdown(truncated_text, code_theme=code_theme, style=style or ""),
            ),
            border_style=ThemeKey.LINES,
        )
    return Panel.fit(NoInsetMarkdown(stripped_result, code_theme=code_theme), border_style=ThemeKey.LINES)
