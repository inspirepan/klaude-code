import json
from pathlib import Path
from typing import Any, cast

from rich.console import Group, RenderableType
from rich.text import Text

from klaude_code.const import DIFF_PREFIX_WIDTH, INVALID_TOOL_CALL_MAX_LENGTH, TAB_EXPAND_WIDTH
from klaude_code.protocol.models import ReadPreviewUIExtra
from klaude_code.tui.components.common import create_grid
from klaude_code.tui.components.rich.theme import ThemeKey
from klaude_code.tui.components.tools._common import MARK_READ, render_path, render_tool_call_tree


def render_read_tool_call(arguments: str) -> RenderableType:
    tool_name = "Read"
    details = Text("", ThemeKey.TOOL_PARAM)

    try:
        payload_raw: Any = json.loads(arguments)
    except json.JSONDecodeError:
        details = Text(
            arguments.strip()[:INVALID_TOOL_CALL_MAX_LENGTH],
            style=ThemeKey.INVALID_TOOL_CALL_ARGS,
        )

        return render_tool_call_tree(mark=MARK_READ, tool_name=tool_name, details=details, overflow="fold")

    if not isinstance(payload_raw, dict):
        details = Text(str(payload_raw)[:INVALID_TOOL_CALL_MAX_LENGTH], style=ThemeKey.INVALID_TOOL_CALL_ARGS)
        return render_tool_call_tree(mark=MARK_READ, tool_name=tool_name, details=details, overflow="fold")

    payload = cast(dict[str, Any], payload_raw)
    file_path = payload.get("file_path")
    limit = payload.get("limit", None)
    offset = payload.get("offset", None)
    offset_int = offset if isinstance(offset, int) and not isinstance(offset, bool) else None
    limit_int = limit if isinstance(limit, int) and not isinstance(limit, bool) else None

    if isinstance(file_path, str) and file_path:
        path_obj = Path(file_path)
        is_skill = path_obj.name == "SKILL.md"
        if is_skill:
            tool_name = "Read Skill"
            path_text = render_path(file_path, ThemeKey.TOOL_PARAM_FILE_PATH)
            skill_file = "SKILL.md"
            skill_file_start = path_text.plain.rfind(skill_file)
            if skill_file_start != -1:
                skill_file_end = skill_file_start + len(skill_file)
                path_text.stylize(ThemeKey.TOOL_PARAM_FILE_PATH_SKILL_FILE, skill_file_start, skill_file_end)

                slash_index = skill_file_start - 1
                if slash_index >= 0 and path_text.plain[slash_index] == "/":
                    skill_name_start = path_text.plain.rfind("/", 0, slash_index) + 1
                    if skill_name_start < slash_index:
                        path_text.stylize(ThemeKey.TOOL_PARAM_FILE_PATH_SKILL_NAME, skill_name_start, slash_index)
            details.append_text(path_text)
        else:
            details.append_text(render_path(file_path, ThemeKey.TOOL_PARAM_FILE_PATH))
    else:
        details.append("(no file_path)", style=ThemeKey.TOOL_PARAM)

    if limit_int is not None and offset_int is not None:
        details = (
            details.append_text(Text(" "))
            .append_text(Text(str(offset_int), ThemeKey.TOOL_PARAM))
            .append_text(Text(":", ThemeKey.TOOL_PARAM))
            .append_text(Text(str(offset_int + limit_int - 1), ThemeKey.TOOL_PARAM))
        )
    elif limit_int is not None and offset is None:
        details = (
            details.append_text(Text(" "))
            .append_text(Text("1", ThemeKey.TOOL_PARAM))
            .append_text(Text(":", ThemeKey.TOOL_PARAM))
            .append_text(Text(str(limit_int), ThemeKey.TOOL_PARAM))
        )
    elif offset_int is not None and limit is None:
        details = (
            details.append_text(Text(" "))
            .append_text(Text(str(offset_int), ThemeKey.TOOL_PARAM))
            .append_text(Text(":", ThemeKey.TOOL_PARAM))
            .append_text(Text("-", ThemeKey.TOOL_PARAM))
        )
    elif offset is not None or limit is not None:
        invalid_parts: list[str] = []
        if offset is not None and (offset_int is None or limit is not None):
            invalid_parts.append(f"offset={offset}")
        if limit is not None and (limit_int is None or offset is not None):
            invalid_parts.append(f"limit={limit}")
        if invalid_parts:
            details.append_text(Text(f" ({', '.join(invalid_parts)})", ThemeKey.INVALID_TOOL_CALL_ARGS))

    return render_tool_call_tree(mark=MARK_READ, tool_name=tool_name, details=details, overflow="fold")

def render_read_preview(ui_extra: ReadPreviewUIExtra) -> RenderableType:
    """Render read preview with line numbers aligned to diff style."""
    grid = create_grid(overflow="ellipsis")
    grid.padding = (0, 0)

    for line in ui_extra.lines:
        prefix = f"{line.line_no:>{DIFF_PREFIX_WIDTH}} "
        content = line.content.expandtabs(TAB_EXPAND_WIDTH)
        grid.add_row(Text(prefix, ThemeKey.TOOL_RESULT), Text(content, ThemeKey.TOOL_RESULT))

    if ui_extra.remaining_lines <= 0:
        return grid

    remaining_prefix = f"{'\u2026':>{DIFF_PREFIX_WIDTH}} "
    remaining_text = Text(
        f"{remaining_prefix}(more {ui_extra.remaining_lines} lines)",
        ThemeKey.TOOL_RESULT_TRUNCATED,
        overflow="ellipsis",
        no_wrap=True,
    )
    return Group(grid, remaining_text)
