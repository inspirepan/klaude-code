from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.style import Style
from rich.text import Text

from klaude_code.protocol import model
from klaude_code.ui.base.theme import ThemeKey
from klaude_code.ui.rich_ext.markdown import NoInsetMarkdown


def render_sub_agent_call(e: model.SubAgentState, style: Style | None = None) -> RenderableType:
    """Render sub-agent tool call header and quoted body."""
    desc = Text(f" {e.sub_agent_desc} ", style=Style(color=style.color if style else None, bold=True, reverse=True))
    return Group(
        Text.assemble((e.sub_agent_type.value, ThemeKey.TOOL_NAME), " ", desc),
        Text(e.sub_agent_prompt, style=style or ""),
    )


def render_sub_agent_result(result: str, *, code_theme: str) -> RenderableType:
    return Panel.fit(NoInsetMarkdown(result, code_theme=code_theme), border_style=ThemeKey.LINES)
