import json
from pathlib import Path
from typing import Any, Literal, cast

from rich.console import RenderableType
from rich.text import Text

from klaude_code.const import INVALID_TOOL_CALL_MAX_LENGTH
from klaude_code.protocol.sub_agent import is_sub_agent_tool as _is_sub_agent_tool
from klaude_code.tui.components.common import create_grid, truncate_middle
from klaude_code.tui.components.rich.quote import TreeQuote
from klaude_code.tui.components.rich.theme import ThemeKey

# Tool markers (Unicode symbols for UI display)
MARK_GENERIC = "\u2692"
MARK_BASH = "$"
MARK_PLAN = "\u25c8"
MARK_READ = "\u2192"
MARK_EDIT = "\u00b1"
MARK_WRITE = "+"
MARK_WEB_FETCH = "\u2192"
MARK_WEB_SEARCH = "\u2731"
MARK_REWIND = "\u21b6"
MARK_QUESTION = "\u25c9"

BASH_OUTPUT_LEFT_PADDING = 7
BASH_TOOL_CALL_DIVIDER_THRESHOLD = 10
BASH_TOOL_CALL_DIVIDER_WIDTH = 12


def is_sub_agent_tool(tool_name: str) -> bool:
    return _is_sub_agent_tool(tool_name)


def get_agent_active_form(arguments: str) -> str:
    """Return active form text for Agent tool based on its arguments."""
    from klaude_code.protocol.sub_agent import get_sub_agent_profile

    _DEFAULT = "Tasking"

    try:
        parsed = json.loads(arguments)
    except json.JSONDecodeError:
        return _DEFAULT

    if not isinstance(parsed, dict):
        return _DEFAULT

    args = cast(dict[str, Any], parsed)

    type_raw = args.get("type")
    if not isinstance(type_raw, str):
        return _DEFAULT

    try:
        profile = get_sub_agent_profile(type_raw.strip())
    except KeyError:
        return _DEFAULT
    return profile.active_form or _DEFAULT


def render_path(path: str, style: str, is_directory: bool = False) -> Text:
    if path.startswith(str(Path().cwd())):
        path = path.replace(str(Path().cwd()), "").lstrip("/")
    elif path.startswith(str(Path().home())):
        path = path.replace(str(Path().home()), "~")
    elif not path.startswith("/") and not path.startswith("."):
        path = "./" + path
    if is_directory:
        path = path.rstrip("/") + "/"
    return Text(path, style=style, overflow="fold")


def render_tool_call_tree(
    *,
    mark: str,
    tool_name: str,
    details: RenderableType | None,
    overflow: Literal["fold", "crop", "ellipsis", "ignore"] = "ellipsis",
) -> RenderableType:
    grid = create_grid(overflow=overflow)
    grid.add_row(
        Text(tool_name, style=ThemeKey.TOOL_NAME),
        details if details is not None else Text(""),
    )

    return TreeQuote.for_tool_call(
        grid,
        mark=mark,
        style=ThemeKey.TOOL_RESULT_TREE_PREFIX,
        style_first=ThemeKey.TOOL_MARK,
    )


def render_generic_tool_call(tool_name: str, arguments: str, markup: str = MARK_GENERIC) -> RenderableType:
    if not arguments:
        return render_tool_call_tree(mark=markup, tool_name=tool_name, details=None)

    details: RenderableType
    try:
        payload = json.loads(arguments)
    except json.JSONDecodeError:
        details = Text(
            arguments.strip()[:INVALID_TOOL_CALL_MAX_LENGTH],
            style=ThemeKey.INVALID_TOOL_CALL_ARGS,
        )
    else:
        if isinstance(payload, dict):
            payload_dict = cast(dict[str, Any], payload)
            if len(payload_dict) == 0:
                details = Text("", ThemeKey.TOOL_PARAM)
            elif len(payload_dict) == 1:
                details = Text(str(next(iter(payload_dict.values()))), ThemeKey.TOOL_PARAM)
            else:
                details = Text(
                    ", ".join([f"{k}: {v}" for k, v in payload_dict.items()]),
                    ThemeKey.TOOL_PARAM,
                )
        else:
            details = Text(str(payload)[:INVALID_TOOL_CALL_MAX_LENGTH], style=ThemeKey.INVALID_TOOL_CALL_ARGS)

    return render_tool_call_tree(mark=markup, tool_name=tool_name, details=details)


def render_generic_tool_result(result: str, *, is_error: bool = False) -> RenderableType:
    """Render a generic tool result as truncated text."""
    style = ThemeKey.ERROR if is_error else ThemeKey.TOOL_RESULT
    text = truncate_middle(result, base_style=style)
    # Tool results should not reflow/wrap; use ellipsis when exceeding terminal width.
    text.no_wrap = True
    text.overflow = "ellipsis"
    return text


def render_fallback_tool_result(tool_name: str, result: str, *, is_error: bool = False) -> RenderableType:
    del tool_name
    return render_generic_tool_result(result, is_error=is_error)
