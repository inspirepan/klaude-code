from rich.console import Console, ConsoleOptions, RenderableType, RenderResult
from rich.measure import Measurement
from rich.table import Table
from rich.text import Text

from klaude_code.protocol import tools
from klaude_code.tui.components.bash_syntax import summarize_bash_command
from klaude_code.tui.components.rich.theme import ThemeKey
from klaude_code.tui.components.tools._common import (
    MARK_BASH,
    MARK_EDIT,
    MARK_GENERIC,
    MARK_LOOK_AT,
    MARK_PLAN,
    MARK_QUESTION,
    MARK_READ,
    MARK_REWIND,
    MARK_WEB_FETCH,
    MARK_WEB_SEARCH,
    MARK_WRITE,
    TOOL_SUBJECT_INDENT,
    render_tool_call_tree,
)
from klaude_code.tui.components.tools._presentation import (
    get_tool_call_presentation,
    one_line,
    parse_tool_arguments,
)

# Width of the Bash description column, in cells (~16 CJK glyphs). Fixed so the
# command column starts at the same offset on every row.
BASH_DESCRIPTION_COLUMN_WIDTH = 32
BASH_COMMAND_MIN_WIDTH = 8
BASH_DESCRIPTION_MIN_TERMINAL_WIDTH = TOOL_SUBJECT_INDENT + BASH_DESCRIPTION_COLUMN_WIDTH + 1 + BASH_COMMAND_MIN_WIDTH

# Compact rows keep the same marks as their expanded tool calls, so a mixed
# block reads as one vocabulary.
_COMPACT_MARKS: dict[str, str] = {
    tools.BASH: MARK_BASH,
    tools.READ: MARK_READ,
    tools.LOOK_AT: MARK_LOOK_AT,
    tools.EDIT: MARK_EDIT,
    tools.APPLY_PATCH: MARK_EDIT,
    tools.WRITE: MARK_WRITE,
    tools.TODO_WRITE: MARK_PLAN,
    tools.WEB_FETCH: MARK_WEB_FETCH,
    tools.WEB_SEARCH: MARK_WEB_SEARCH,
    tools.REWIND: MARK_REWIND,
    tools.ASK_USER_QUESTION: MARK_QUESTION,
}


def _clamp_subject(value: str, max_chars: int | None, *, include_mark: bool) -> str:
    if max_chars is None:
        return value
    if len(value) <= max_chars:
        return value
    if not include_mark:
        return value[:max_chars].rstrip()
    return value[: max(1, max_chars - 1)].rstrip() + "…"


def render_compact_tool_activity(
    tool_name: str,
    arguments: str,
    *,
    display_name: str | None = None,
    status: str | None = None,
    max_target_chars: int | None = 40,
    include_truncation_mark: bool = True,
    summarize_bash: bool = True,
) -> Text:
    """Render one compact tool activity line."""

    presentation = get_tool_call_presentation(tool_name, arguments)
    line = Text(no_wrap=True, overflow="ellipsis")
    line.append(display_name or presentation.name, style=ThemeKey.TOOL_NAME)
    if tool_name == tools.BASH:
        args = parse_tool_arguments(arguments)
        description = one_line(args.get("description", ""))
        raw_command = str(args.get("command", ""))
        command_lines = raw_command.splitlines()
        command = (
            summarize_bash_command(raw_command)
            if summarize_bash
            else (command_lines[0].strip() if command_lines else "")
        )
        target = " ".join(part for part in (description, command) if part)
        target = _clamp_subject(target, max_target_chars, include_mark=include_truncation_mark)
        if target:
            line.append(" ")
            _append_compact_bash_target(line, target, description)
        _append_status(line, status)
        return line

    target = presentation.subject
    target_style = ThemeKey.TOOL_PARAM_FILE_PATH if presentation.subject_kind == "path" else ThemeKey.TOOL_PARAM
    target = _clamp_subject(target, max_target_chars, include_mark=include_truncation_mark)
    if target:
        line.append(" ")
        line.append(target, style=target_style)
    _append_status(line, status)
    return line


def render_compact_tool_result(
    tool_name: str,
    arguments: str,
    result: str,
    *,
    status: str,
    exit_code: int | None = None,
) -> RenderableType:
    """Render one stable compact tool result line."""

    details = Text(no_wrap=True, overflow="ellipsis")
    description = ""
    presentation = get_tool_call_presentation(tool_name, arguments)
    if tool_name == tools.BASH:
        description, command_summary = _bash_parts(parse_tool_arguments(arguments))
        if command_summary:
            details.append(command_summary, style=ThemeKey.BASH_ARGUMENT)
    else:
        target = presentation.subject
        target_style = ThemeKey.TOOL_PARAM_FILE_PATH if presentation.subject_kind == "path" else ThemeKey.TOOL_PARAM
        if target:
            details.append(target, style=target_style)
    display_status = "error" if exit_code not in (None, 0) else status
    _append_status(details, display_status)
    if exit_code not in (None, 0):
        details.append(f" exit {exit_code}", style=ThemeKey.ERROR_DIM)
    elif display_status in ("error", "aborted"):
        error = next((line.strip() for line in result.splitlines() if line.strip()), "")
        if error:
            details.append(" · ", style=ThemeKey.METADATA_DIM)
            details.append(error, style=ThemeKey.ERROR)

    return render_tool_call_tree(
        mark=_COMPACT_MARKS.get(tool_name, MARK_GENERIC),
        tool_name=presentation.name,
        details=_with_description_column(description, details) if tool_name == tools.BASH else details,
    )


class _BashDetails:
    def __init__(self, description: str, subject: Text) -> None:
        self.description = description
        self.subject = subject

    def _renderable(self, terminal_width: int) -> RenderableType:
        if terminal_width < BASH_DESCRIPTION_MIN_TERMINAL_WIDTH:
            return self.subject
        grid = Table.grid(padding=(0, 1))
        grid.add_column(width=BASH_DESCRIPTION_COLUMN_WIDTH, no_wrap=True, overflow="ellipsis")
        grid.add_column(overflow="ellipsis")
        grid.add_row(Text(self.description, style=ThemeKey.BASH_TOOL_DESCRIPTION), self.subject)
        return grid

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        yield from console.render(self._renderable(console.width), options)

    def __rich_measure__(self, console: Console, options: ConsoleOptions) -> Measurement:
        return Measurement.get(console, options, self._renderable(console.width))


def _with_description_column(description: str, subject: Text) -> RenderableType:
    """Align Bash descriptions while preserving commands on narrow terminals."""
    return _BashDetails(description, subject) if description else subject


def _bash_parts(args: dict[str, object]) -> tuple[str, str]:
    description = one_line(args.get("description", ""))
    command = str(args.get("command", ""))
    return description, summarize_bash_command(command)


def _append_compact_bash_target(line: Text, target: str, description: str) -> None:
    if not description:
        line.append(target, style=ThemeKey.BASH_ARGUMENT)
        return
    description_length = min(len(description), len(target))
    line.append(target[:description_length], style=ThemeKey.BASH_TOOL_DESCRIPTION)
    remainder = target[description_length:]
    separator_length = len(remainder) - len(remainder.lstrip())
    if separator_length:
        line.append(remainder[:separator_length])
    if remainder[separator_length:]:
        line.append(remainder[separator_length:], style=ThemeKey.BASH_ARGUMENT)


def _append_status(line: Text, status: str | None) -> None:
    if status == "success":
        line.append(" ")
        # Success is the common case: keep it quiet so failures are the only thing that jumps.
        line.append("✓", style=ThemeKey.METADATA_GREEN_DIM)
    elif status == "error":
        line.append(" ")
        line.append("✗", style=ThemeKey.ERROR_BOLD)
    elif status == "aborted":
        line.append(" cancelled", style=ThemeKey.INTERRUPT)
