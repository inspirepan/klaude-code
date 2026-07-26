import json
from typing import Any, Literal, cast

from rich.console import Console, ConsoleOptions, RenderableType, RenderResult
from rich.measure import Measurement
from rich.padding import Padding
from rich.text import Text

from klaude_code.const import INVALID_TOOL_CALL_MAX_LENGTH
from klaude_code.protocol.sub_agent import is_sub_agent_tool as _is_sub_agent_tool
from klaude_code.tui.components.common import create_grid, shorten_path, truncate_middle, truncate_middle_lines
from klaude_code.tui.components.rich.quote import TreeQuote
from klaude_code.tui.components.rich.theme import ThemeKey
from klaude_code.tui.transcript_detail import Detail

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

BASH_TOOL_CALL_DIVIDER_THRESHOLD = 10
BASH_TOOL_CALL_DIVIDER_WIDTH = 12
FULL_TOOL_RESULT_MAX_LINES = 10
SUB_AGENT_FULL_TOOL_RESULT_MAX_LINES = 6

# The tool block sits one level below the assistant narration: the assistant's
# bullet occupies column 0 and its prose column 2, so tool marks start at column 2.
TOOL_GROUP_INDENT = 2
# Pads short tool names ("Bash", "Read") so the subject column lines up across rows.
# Longer names ("Update To-Dos") simply push their own subject right.
TOOL_NAME_COLUMN_WIDTH = 6
# Column where a tool's subject (command, path, query) starts: group indent, the
# "$ " mark, the name column, and the grid's cell padding. Textual tool output
# lines up here too, directly under the arguments it came from.
TOOL_SUBJECT_INDENT = TOOL_GROUP_INDENT + 2 + TOOL_NAME_COLUMN_WIDTH + 2
# Block-level results (panels) stay shallower: their border already sets them
# apart, and a deep indent would just eat width.
TOOL_RESULT_INDENT = TOOL_GROUP_INDENT + 2
BASH_OUTPUT_LEFT_PADDING = TOOL_SUBJECT_INDENT
# Below this, the indent gives way rather than squeezing content to nothing.
MIN_INDENTED_CONTENT_WIDTH = 8

ToolResultStatus = Literal["success", "error", "aborted"]


class AdaptiveIndent:
    """Left indent that yields on narrow terminals instead of crushing the content."""

    def __init__(self, renderable: RenderableType, indent: int) -> None:
        self.renderable = renderable
        self.indent = indent

    def _effective_indent(self, max_width: int) -> int:
        return max(0, min(self.indent, max_width - MIN_INDENTED_CONTENT_WIDTH))

    def __rich_console__(self, console: "Console", options: "ConsoleOptions") -> "RenderResult":
        padded = Padding(self.renderable, (0, 0, 0, self._effective_indent(options.max_width)), expand=False)
        yield from console.render(padded, options)

    def __rich_measure__(self, console: "Console", options: "ConsoleOptions") -> Measurement:
        indent = self._effective_indent(options.max_width)
        inner = Measurement.get(console, options.update(width=max(1, options.max_width - indent)), self.renderable)
        return Measurement(
            min(options.max_width, inner.minimum + indent),
            min(options.max_width, inner.maximum + indent),
        )


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
    path = shorten_path(path)
    if not path.startswith(("/", ".", "~")):
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
    grid = create_grid(overflow=overflow, label_min_width=TOOL_NAME_COLUMN_WIDTH)
    grid.add_row(
        Text(tool_name, style=ThemeKey.TOOL_NAME),
        details if details is not None else Text(""),
    )

    return Padding(
        TreeQuote.for_tool_call(
            grid,
            mark=mark,
            style=ThemeKey.TOOL_RESULT_TREE_PREFIX,
            style_first=ThemeKey.TOOL_MARK,
        ),
        (0, 0, 0, TOOL_GROUP_INDENT),
        expand=False,
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


def tool_result_style(status: ToolResultStatus, *, success_style: str = ThemeKey.TOOL_RESULT) -> str:
    if status == "aborted":
        return ThemeKey.INTERRUPT
    if status == "error":
        return ThemeKey.ERROR
    return success_style


def render_generic_tool_result(
    result: str,
    *,
    status: ToolResultStatus = "success",
    detail: Detail = Detail.COMPACT,
    max_lines: int = FULL_TOOL_RESULT_MAX_LINES,
) -> RenderableType:
    """Render a generic tool result at the requested transcript detail."""
    style = tool_result_style(status)
    if not detail.is_compact:
        return truncate_middle_lines(result, max_lines=max_lines, base_style=style)

    text = truncate_middle(result, base_style=style)
    # Tool results should not reflow/wrap; use ellipsis when exceeding terminal width.
    text.no_wrap = True
    text.overflow = "ellipsis"
    return text


def render_fallback_tool_result(
    tool_name: str,
    result: str,
    *,
    status: ToolResultStatus = "success",
    detail: Detail = Detail.COMPACT,
    max_lines: int = FULL_TOOL_RESULT_MAX_LINES,
) -> RenderableType:
    del tool_name
    return render_generic_tool_result(result, status=status, detail=detail, max_lines=max_lines)
