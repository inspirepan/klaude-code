import json
from typing import Any, cast

from rich import box
from rich.console import Group, RenderableType
from rich.json import JSON
from rich.panel import Panel
from rich.style import Style
from rich.text import Text

from klaude_code.const import SUB_AGENT_RESULT_MAX_LINES
from klaude_code.protocol import events, model
from klaude_code.protocol.sub_agent import get_sub_agent_profile_by_tool
from klaude_code.ui.renderers.common import truncate_head
from klaude_code.ui.rich.markdown import NoInsetMarkdown
from klaude_code.ui.rich.theme import ThemeKey


def _compact_schema_value(value: dict[str, Any]) -> str | list[Any] | dict[str, Any]:
    """Convert a JSON Schema value to compact representation."""
    value_type = value.get("type", "any").lower()
    desc = value.get("description", "")

    if value_type == "object":
        props = value.get("properties", {})
        return {k: _compact_schema_value(v) for k, v in props.items()}
    elif value_type == "array":
        items = value.get("items", {})
        # If items have no description, use the array's description
        if desc and not items.get("description"):
            items = {**items, "description": desc}
        return [_compact_schema_value(items)]
    else:
        if desc:
            return f"{value_type} // {desc}"
        return value_type


def _compact_schema(schema: dict[str, Any]) -> dict[str, Any] | list[Any] | str:
    """Convert JSON Schema to compact representation for display."""
    return _compact_schema_value(schema)


def render_sub_agent_call(e: model.SubAgentState, style: Style | None = None) -> RenderableType:
    """Render sub-agent tool call header and prompt body."""
    desc = Text(
        f" {e.sub_agent_desc} ",
        style=Style(color=style.color if style else None, bold=True, reverse=True),
    )
    resume_note = Text("")
    if e.resume:
        resume_note = Text(
            f" resume:{e.resume[:7]} ",
            style=Style(color=style.color if style else None, dim=True),
        )
    elements: list[RenderableType] = [
        Text.assemble((e.sub_agent_type, ThemeKey.TOOL_NAME), " ", desc, resume_note),
        truncate_head(e.sub_agent_prompt, base_style=style or "", truncated_style=ThemeKey.STATUS_HINT),
    ]
    if e.output_schema:
        elements.append(Text("\nExpected Output Format JSON:", style=style or ""))
        compact = _compact_schema(e.output_schema)
        schema_text = json.dumps(compact, ensure_ascii=False, indent=2)
        elements.append(JSON(schema_text))
    return Group(*elements)


def _extract_agent_id_footer(text: str) -> tuple[str, str | None]:
    """Extract agentId footer from result text if present.

    Returns (main_content, footer_line) where footer_line is None if not found.
    """
    lines = text.rstrip().splitlines()
    if len(lines) >= 2 and lines[-1].startswith("agentId:"):
        # Check if there's an empty line before the footer
        if lines[-2] == "":
            return "\n".join(lines[:-2]), lines[-1]
        return "\n".join(lines[:-1]), lines[-1]
    return text, None


def render_sub_agent_result(
    result: str,
    *,
    code_theme: str,
    style: Style | None = None,
    has_structured_output: bool = False,
    description: str | None = None,
    panel_style: Style | None = None,
) -> RenderableType:
    stripped_result = result.strip()
    result_panel_style = panel_style or ThemeKey.SUB_AGENT_RESULT_PANEL

    # Extract agentId footer for separate styling
    main_content, agent_id_footer = _extract_agent_id_footer(stripped_result)
    stripped_result = main_content.strip()

    # Use rich JSON for structured output
    if has_structured_output:
        try:
            group_elements: list[RenderableType] = [
                Text(
                    "use /export to view full output",
                    style=ThemeKey.TOOL_RESULT,
                ),
                JSON(stripped_result),
            ]
            if description:
                group_elements.insert(0, NoInsetMarkdown(f"# {description}", code_theme=code_theme, style=style or ""))
            if agent_id_footer:
                group_elements.append(Text(agent_id_footer, style=ThemeKey.SUB_AGENT_FOOTER))
            return Panel.fit(
                Group(*group_elements),
                box=box.SIMPLE,
                border_style=ThemeKey.LINES,
                style=result_panel_style,
            )
        except json.JSONDecodeError:
            # Fall back to markdown if not valid JSON
            pass

    # Add markdown heading if description is provided for non-structured output
    if description:
        stripped_result = f"# {description}\n\n{stripped_result}"

    lines = stripped_result.splitlines()
    if len(lines) > SUB_AGENT_RESULT_MAX_LINES:
        hidden_count = len(lines) - SUB_AGENT_RESULT_MAX_LINES
        head_count = SUB_AGENT_RESULT_MAX_LINES // 2
        tail_count = SUB_AGENT_RESULT_MAX_LINES - head_count
        head_text = "\n".join(lines[:head_count])
        tail_text = "\n".join(lines[-tail_count:])
        truncated_elements: list[RenderableType] = [
            NoInsetMarkdown(head_text, code_theme=code_theme, style=style or ""),
            Text(
                f"\n( … more {hidden_count} lines — use /export to view full output )\n",
                style=ThemeKey.TOOL_RESULT_TRUNCATED,
            ),
            NoInsetMarkdown(tail_text, code_theme=code_theme, style=style or ""),
        ]
        if agent_id_footer:
            truncated_elements.append(Text(agent_id_footer, style=ThemeKey.SUB_AGENT_FOOTER))
        return Panel.fit(
            Group(*truncated_elements),
            box=box.SIMPLE,
            border_style=ThemeKey.LINES,
            style=result_panel_style,
        )
    normal_elements: list[RenderableType] = [NoInsetMarkdown(stripped_result, code_theme=code_theme)]
    if agent_id_footer:
        normal_elements.append(Text(agent_id_footer, style=ThemeKey.SUB_AGENT_FOOTER))
    return Panel.fit(
        Group(*normal_elements),
        box=box.SIMPLE,
        border_style=ThemeKey.LINES,
        style=result_panel_style,
    )


def build_sub_agent_state_from_tool_call(e: events.ToolCallEvent) -> model.SubAgentState | None:
    """Build SubAgentState from a tool call event for replay rendering."""
    profile = get_sub_agent_profile_by_tool(e.tool_name)
    if profile is None:
        return None
    description = profile.name
    prompt = ""
    output_schema: dict[str, Any] | None = None
    resume: str | None = None
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
        resume_value = payload.get("resume")
        if isinstance(resume_value, str) and resume_value.strip():
            resume = resume_value.strip()
        # Extract output_schema if profile supports it
        if profile.output_schema_arg:
            schema_value = payload.get(profile.output_schema_arg)
            if isinstance(schema_value, dict):
                output_schema = cast(dict[str, Any], schema_value)
    return model.SubAgentState(
        sub_agent_type=profile.name,
        sub_agent_desc=description,
        sub_agent_prompt=prompt,
        resume=resume,
        output_schema=output_schema,
    )
