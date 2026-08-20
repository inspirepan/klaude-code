import json
from typing import Any, cast

from rich.console import Group, RenderableType
from rich.text import Text

from klaude_code.const import INVALID_TOOL_CALL_MAX_LENGTH, QUERY_DISPLAY_TRUNCATE_LENGTH
from klaude_code.protocol import tools
from klaude_code.tui.components.rich.theme import ThemeKey
from klaude_code.tui.components.tools._common import MARK_LOOK_AT, render_path, render_tool_call_tree
from klaude_code.tui.components.tools._presentation import get_tool_display_name, one_line


def render_look_at_tool_call(arguments: str) -> RenderableType:
    tool_name = get_tool_display_name(tools.LOOK_AT, arguments)

    try:
        payload_raw: Any = json.loads(arguments)
    except json.JSONDecodeError:
        details: RenderableType = Text(
            arguments.strip()[:INVALID_TOOL_CALL_MAX_LENGTH],
            style=ThemeKey.INVALID_TOOL_CALL_ARGS,
        )
        return render_tool_call_tree(mark=MARK_LOOK_AT, tool_name=tool_name, details=details, overflow="fold")

    if not isinstance(payload_raw, dict):
        details = Text(str(payload_raw)[:INVALID_TOOL_CALL_MAX_LENGTH], style=ThemeKey.INVALID_TOOL_CALL_ARGS)
        return render_tool_call_tree(mark=MARK_LOOK_AT, tool_name=tool_name, details=details, overflow="fold")

    payload = cast(dict[str, Any], payload_raw)
    file_path = payload.get("file_path")
    question = payload.get("question")
    region = payload.get("region")

    subject = Text(overflow="fold")
    if isinstance(file_path, str) and file_path:
        subject.append_text(render_path(file_path, ThemeKey.TOOL_PARAM_FILE_PATH))
    else:
        subject.append("(no file_path)", style=ThemeKey.TOOL_PARAM)
    if isinstance(region, list) and len(region) == 4:
        coords = cast(list[Any], region)
        subject.append(
            f" [{coords[0]},{coords[1]} → {coords[2]},{coords[3]}]",
            style=ThemeKey.TOOL_TIMEOUT,
        )

    sections: list[RenderableType] = [subject]
    if isinstance(question, str) and question.strip():
        display_question = one_line(question.strip())
        if len(display_question) > QUERY_DISPLAY_TRUNCATE_LENGTH:
            display_question = display_question[: QUERY_DISPLAY_TRUNCATE_LENGTH - 1] + "…"
        sections.append(Text(display_question, style=ThemeKey.TOOL_PARAM_QUESTION, no_wrap=True, overflow="ellipsis"))

    return render_tool_call_tree(mark=MARK_LOOK_AT, tool_name=tool_name, details=Group(*sections))
