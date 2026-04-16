import json
from typing import Any, cast

from rich.console import Group, RenderableType
from rich.padding import Padding
from rich.text import Text

from klaude_code.const import INVALID_TOOL_CALL_MAX_LENGTH
from klaude_code.tui.components.bash_syntax import highlight_bash_command
from klaude_code.tui.components.rich.theme import ThemeKey
from klaude_code.tui.components.tools._common import (
    BASH_OUTPUT_LEFT_PADDING,
    BASH_TOOL_CALL_DIVIDER_THRESHOLD,
    BASH_TOOL_CALL_DIVIDER_WIDTH,
    MARK_BASH,
    render_tool_call_tree,
)


def render_bash_tool_call(arguments: str) -> RenderableType:
    tool_name = "Bash"

    try:
        payload_raw: Any = json.loads(arguments) if arguments else {}
    except json.JSONDecodeError:
        details: RenderableType = Text(
            arguments.strip()[:INVALID_TOOL_CALL_MAX_LENGTH],
            style=ThemeKey.INVALID_TOOL_CALL_ARGS,
        )
        return render_tool_call_tree(mark=MARK_BASH, tool_name=tool_name, details=details)

    if not isinstance(payload_raw, dict):
        details = Text(
            str(payload_raw)[:INVALID_TOOL_CALL_MAX_LENGTH],
            style=ThemeKey.INVALID_TOOL_CALL_ARGS,
        )
        return render_tool_call_tree(mark=MARK_BASH, tool_name=tool_name, details=details)

    payload: dict[str, object] = cast(dict[str, object], payload_raw)

    command = payload.get("command")
    description = payload.get("description")
    if isinstance(command, str) and command.strip():
        cmd_str = command.strip()
        highlighted = highlight_bash_command(cmd_str)
        sections: list[RenderableType] = []
        if isinstance(description, str) and description.strip():
            description_text = Text(f"# {description.strip()}", style=ThemeKey.BASH_TOOL_DESCRIPTION, overflow="fold")
            sections.append(description_text)
        sections.append(Padding(highlighted, pad=0, style=ThemeKey.CODE_BACKGROUND, expand=False))
        if len(cmd_str.splitlines()) > BASH_TOOL_CALL_DIVIDER_THRESHOLD:
            sections.append(Text("\u2500" * BASH_TOOL_CALL_DIVIDER_WIDTH, style=ThemeKey.LINES_DIM))
        return render_tool_call_tree(mark=MARK_BASH, tool_name=tool_name, details=Group(*sections))

    return render_tool_call_tree(mark=MARK_BASH, tool_name=tool_name, details=None)


def indent_bash_output(content: RenderableType) -> RenderableType:
    return Padding(content, (0, 0, 0, BASH_OUTPUT_LEFT_PADDING))
