import json
from typing import Any, cast

from rich.console import RenderableType
from rich.text import Text

from klaude_code.protocol import tools
from klaude_code.tui.components.bash_syntax import summarize_bash_command
from klaude_code.tui.components.common import format_pascal_case
from klaude_code.tui.components.rich.theme import ThemeKey
from klaude_code.tui.components.tools._common import MARK_BASH, MARK_GENERIC, render_tool_call_tree


def _tool_arguments(arguments: str) -> dict[str, object]:
    try:
        value: Any = json.loads(arguments)
    except json.JSONDecodeError:
        return {}
    return cast(dict[str, object], value) if isinstance(value, dict) else {}


def _one_line(value: object) -> str:
    return " ".join(str(value).replace("\\\n", " ").split())


def _clamp_subject(value: str, max_chars: int | None, *, include_mark: bool) -> str:
    if max_chars is None:
        return value
    if len(value) <= max_chars:
        return value
    if not include_mark:
        return value[:max_chars].rstrip()
    return value[: max(1, max_chars - 1)].rstrip() + "…"


def _tool_target(tool_name: str, arguments: str) -> tuple[str, str | ThemeKey]:
    args = _tool_arguments(arguments)
    target = ""
    target_style: str | ThemeKey = ThemeKey.TOOL_PARAM

    if tool_name == tools.READ:
        target = _one_line(args.get("file_path", ""))
        offset = args.get("offset")
        limit = args.get("limit")
        if target and isinstance(offset, int):
            start = max(1, offset)
            target += f":{start}"
            if isinstance(limit, int) and limit > 0:
                target += f"-{start + limit - 1}"
        target_style = ThemeKey.TOOL_PARAM_FILE_PATH
    elif tool_name in (tools.EDIT, tools.WRITE):
        target = _one_line(args.get("file_path", ""))
        target_style = ThemeKey.TOOL_PARAM_FILE_PATH
    elif tool_name == tools.BASH:
        description, command_summary = _bash_parts(args)
        target = "  ".join(part for part in (description, command_summary) if part)
        target_style = ThemeKey.BASH_TOOL_DESCRIPTION if description else ThemeKey.BASH_COMMAND
    elif tool_name == tools.WEB_SEARCH:
        target = _one_line(args.get("query", ""))
    elif tool_name == tools.WEB_FETCH:
        target = _one_line(args.get("url", ""))
        target_style = ThemeKey.TOOL_PARAM_FILE_PATH
    else:
        for key in ("description", "query", "file_path", "path", "url", "command"):
            if args.get(key):
                target = _one_line(args[key])
                break

    return target, target_style


def render_compact_tool_activity(
    tool_name: str,
    arguments: str,
    *,
    status: str | None = None,
    max_target_chars: int | None = 40,
    include_truncation_mark: bool = True,
) -> Text:
    """Render one compact tool activity line."""

    line = Text()
    line.append(format_pascal_case(tool_name), style=ThemeKey.TOOL_NAME)
    if tool_name == tools.BASH:
        description, command_summary = _bash_parts(_tool_arguments(arguments))
        target = "  ".join(part for part in (description, command_summary) if part)
        target = _clamp_subject(target, max_target_chars, include_mark=include_truncation_mark)
        if target:
            line.append(" ")
            _append_compact_bash_target(line, target, description)
        _append_status(line, status)
        return line

    target, target_style = _tool_target(tool_name, arguments)
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
    if tool_name == tools.BASH:
        description, command_summary = _bash_parts(_tool_arguments(arguments))
        if description:
            details.append(description, style=ThemeKey.BASH_TOOL_DESCRIPTION)
        if command_summary:
            if details.plain:
                details.append("  ")
            details.append(command_summary, style=ThemeKey.BASH_ARGUMENT)
    else:
        target, target_style = _tool_target(tool_name, arguments)
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
        mark=MARK_BASH if tool_name == tools.BASH else MARK_GENERIC,
        tool_name=format_pascal_case(tool_name),
        details=details,
    )


def _bash_parts(args: dict[str, object]) -> tuple[str, str]:
    description = _one_line(args.get("description", ""))
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
        line.append("✓", style=ThemeKey.METADATA_GREEN)
    elif status == "error":
        line.append(" ")
        line.append("✗", style=ThemeKey.ERROR_BOLD)
    elif status == "aborted":
        line.append(" cancelled", style=ThemeKey.INTERRUPT)
