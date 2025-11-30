import json

from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.style import Style
from rich.text import Text

from klaude_code import const
from klaude_code.protocol.sub_agent import get_sub_agent_profile_by_tool
from klaude_code.protocol import events, model
from klaude_code.ui.rich.markdown import NoInsetMarkdown
from klaude_code.ui.rich.theme import ThemeKey


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
    if len(lines) > const.SUB_AGENT_RESULT_MAX_LINES:
        hidden_count = len(lines) - const.SUB_AGENT_RESULT_MAX_LINES
        truncated_text = "\n".join(lines[-const.SUB_AGENT_RESULT_MAX_LINES :])
        return Panel.fit(
            Group(
                Text(
                    f"… more {hidden_count} lines — use /export to view full output",
                    style=ThemeKey.TOOL_RESULT,
                ),
                NoInsetMarkdown(truncated_text, code_theme=code_theme, style=style or ""),
            ),
            border_style=ThemeKey.LINES,
        )
    return Panel.fit(
        NoInsetMarkdown(stripped_result, code_theme=code_theme),
        border_style=ThemeKey.LINES,
    )


def build_sub_agent_state_from_tool_call(e: events.ToolCallEvent) -> model.SubAgentState | None:
    """Build SubAgentState from a tool call event for replay rendering."""
    profile = get_sub_agent_profile_by_tool(e.tool_name)
    if profile is None:
        return None
    description = profile.name
    prompt = ""
    if e.arguments:
        try:
            payload: dict[str, object] = json.loads(e.arguments)
        except json.JSONDecodeError:
            payload = {}
        desc_value = payload.get("description")
        if isinstance(desc_value, str) and desc_value.strip():
            description = desc_value.strip()
        prompt_value = payload.get("prompt") or payload.get("task")
        if isinstance(prompt_value, str):
            prompt = prompt_value.strip()
    return model.SubAgentState(
        sub_agent_type=profile.name,
        sub_agent_desc=description,
        sub_agent_prompt=prompt,
    )
