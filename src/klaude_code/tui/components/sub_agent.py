import json
from typing import Any

from rich.console import Group, RenderableType
from rich.json import JSON
from rich.style import Style
from rich.text import Text

from klaude_code.const import SUB_AGENT_RESULT_MAX_LINES
from klaude_code.protocol import model
from klaude_code.tui.components.common import truncate_head
from klaude_code.tui.components.rich.theme import ThemeKey


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
        truncate_head(e.sub_agent_prompt, base_style=style or "", truncated_style=ThemeKey.STATUS_HINT, max_lines=10),
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
    has_structured_output: bool = False,
    description: str | None = None,
    sub_agent_color: Style | None = None,
) -> RenderableType:
    stripped_result = result.strip()
    main_content, agent_id_footer = _extract_agent_id_footer(stripped_result)
    stripped_result = main_content.strip()

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

    # Try structured JSON output first
    use_text_rendering = True
    if has_structured_output:
        try:
            elements.append(Text("use /export to view full output", style=ThemeKey.TOOL_RESULT_TRUNCATED))
            elements.append(JSON(stripped_result))
            use_text_rendering = False
        except json.JSONDecodeError:
            pass

    # Text rendering (either fallback or non-structured)
    if use_text_rendering:
        if not stripped_result:
            return Text()

        lines = stripped_result.splitlines()
        if len(lines) > SUB_AGENT_RESULT_MAX_LINES:
            hidden_count = len(lines) - SUB_AGENT_RESULT_MAX_LINES
            elements.append(Text(f"( ... more {hidden_count} lines)", style=ThemeKey.TOOL_RESULT_TRUNCATED))
            elements.append(Text("\n".join(lines[-SUB_AGENT_RESULT_MAX_LINES:]), style=ThemeKey.TOOL_RESULT))
        else:
            elements.append(Text(stripped_result, style=ThemeKey.TOOL_RESULT))

    if agent_id_footer:
        elements.append(Text(agent_id_footer, style=ThemeKey.SUB_AGENT_FOOTER))

    return Group(*elements)
