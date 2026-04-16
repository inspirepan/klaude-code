import json
from typing import Any

from rich.console import RenderableType
from rich.text import Text

from klaude_code.const import INVALID_TOOL_CALL_MAX_LENGTH
from klaude_code.tui.components.rich.theme import ThemeKey
from klaude_code.tui.components.tools._common import MARK_REWIND, render_tool_call_tree


def render_rewind_tool_call(arguments: str) -> RenderableType:
    tool_name = "Rewind"

    try:
        payload: dict[str, Any] = json.loads(arguments)
    except json.JSONDecodeError:
        details = Text(
            arguments.strip()[:INVALID_TOOL_CALL_MAX_LENGTH],
            style=ThemeKey.INVALID_TOOL_CALL_ARGS,
        )
        return render_tool_call_tree(mark=MARK_REWIND, tool_name=tool_name, details=details)

    checkpoint_id = payload.get("checkpoint_id")
    rationale = payload.get("rationale", "")

    summary = Text("", ThemeKey.TOOL_PARAM)
    if isinstance(checkpoint_id, int):
        summary.append(f"Checkpoint {checkpoint_id}", ThemeKey.TOOL_PARAM_BOLD)
    if rationale:
        rationale_preview = rationale if len(rationale) <= 50 else rationale[:47] + "..."
        if summary.plain:
            summary.append(" - ")
        summary.append(rationale_preview, ThemeKey.TOOL_PARAM)

    return render_tool_call_tree(mark=MARK_REWIND, tool_name=tool_name, details=summary if summary.plain else None)
