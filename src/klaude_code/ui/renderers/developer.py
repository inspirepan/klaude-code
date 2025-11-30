from rich.console import Group, RenderableType
from rich.padding import Padding
from rich.table import Table
from rich.text import Text

from klaude_code.protocol import commands, events, model
from klaude_code.ui.renderers import diffs as r_diffs
from klaude_code.ui.renderers.common import create_grid
from klaude_code.ui.renderers.tools import render_path
from klaude_code.ui.rich.theme import ThemeKey
from klaude_code.ui.utils.common import truncate_display


def need_render_developer_message(e: events.DeveloperMessageEvent) -> bool:
    return bool(
        e.item.memory_paths
        or e.item.external_file_changes
        or e.item.todo_use
        or e.item.at_files
        or e.item.user_image_count
    )


def render_developer_message(e: events.DeveloperMessageEvent) -> RenderableType:
    """Render developer message details into a single group.

    Includes: memory paths, external file changes, todo reminder, @file operations.
    Command output is excluded; render it separately via `render_command_output`.
    """
    parts: list[RenderableType] = []

    if mp := e.item.memory_paths:
        grid = create_grid()
        grid.add_row(
            Text("  +", style=ThemeKey.REMINDER),
            Text.assemble(
                ("Load memory ", ThemeKey.REMINDER),
                Text(", ", ThemeKey.REMINDER).join(
                    render_path(memory_path, ThemeKey.REMINDER_BOLD) for memory_path in mp
                ),
            ),
        )
        parts.append(grid)

    if fc := e.item.external_file_changes:
        grid = create_grid()
        for file_path in fc:
            grid.add_row(
                Text("  +", style=ThemeKey.REMINDER),
                Text.assemble(
                    ("Read ", ThemeKey.REMINDER),
                    render_path(file_path, ThemeKey.REMINDER_BOLD),
                    (" after external changes", ThemeKey.REMINDER),
                ),
            )
        parts.append(grid)

    if e.item.todo_use:
        grid = create_grid()
        grid.add_row(
            Text("  +", style=ThemeKey.REMINDER),
            Text("Todo hasn't been updated recently", ThemeKey.REMINDER),
        )
        parts.append(grid)

    if e.item.at_files:
        grid = create_grid()
        for at_file in e.item.at_files:
            grid.add_row(
                Text("  +", style=ThemeKey.REMINDER),
                Text.assemble(
                    (f"{at_file.operation} ", ThemeKey.REMINDER),
                    render_path(at_file.path, ThemeKey.REMINDER_BOLD),
                ),
            )
        parts.append(grid)

    if uic := e.item.user_image_count:
        grid = create_grid()
        grid.add_row(
            Text("  +", style=ThemeKey.REMINDER),
            Text(f"Attached {uic} image{'s' if uic > 1 else ''}", style=ThemeKey.REMINDER),
        )
        parts.append(grid)

    return Group(*parts) if parts else Text("")


def render_command_output(e: events.DeveloperMessageEvent) -> RenderableType:
    """Render developer command output content."""
    if not e.item.command_output:
        return Text("")

    match e.item.command_output.command_name:
        case commands.CommandName.DIFF:
            if e.item.content is None or len(e.item.content) == 0:
                return Padding.indent(Text("(no changes)", style=ThemeKey.TOOL_RESULT), level=2)
            return r_diffs.render_diff_panel(e.item.content, show_file_name=True)
        case commands.CommandName.HELP:
            return Padding.indent(Text.from_markup(e.item.content or ""), level=2)
        case commands.CommandName.STATUS:
            return _render_status_output(e.item.command_output)
        case _:
            content = e.item.content or "(no content)"
            style = ThemeKey.TOOL_RESULT if not e.item.command_output.is_error else ThemeKey.ERROR
            return Padding.indent(Text(truncate_display(content), style=style), level=2)


def _format_tokens(tokens: int) -> str:
    """Format token count with K/M suffix for readability."""
    if tokens >= 1_000_000:
        return f"{tokens / 1_000_000:.2f}M"
    if tokens >= 1_000:
        return f"{tokens / 1_000:.1f}K"
    return str(tokens)


def _format_cost(cost: float | None) -> str:
    """Format cost in USD."""
    if cost is None:
        return "-"
    if cost < 0.01:
        return f"${cost:.4f}"
    return f"${cost:.2f}"


def _render_status_output(command_output: model.CommandOutput) -> RenderableType:
    """Render session status as a two-column table with sections."""
    if not command_output.ui_extra or not command_output.ui_extra.session_status:
        return Text("(no status data)", style=ThemeKey.TOOL_RESULT)

    status = command_output.ui_extra.session_status
    usage = status.usage

    table = Table.grid(padding=(0, 2))
    table.add_column(style=ThemeKey.TOOL_RESULT, no_wrap=True)
    table.add_column(style=ThemeKey.TOOL_RESULT, no_wrap=True)
    # Token Usage section
    table.add_row(Text("Token Usage", style="bold"), "")
    table.add_row("Input Tokens", _format_tokens(usage.input_tokens))
    if usage.cached_tokens > 0:
        table.add_row("Cached Tokens", _format_tokens(usage.cached_tokens))
    if usage.reasoning_tokens > 0:
        table.add_row("Reasoning Tokens", _format_tokens(usage.reasoning_tokens))
    table.add_row("Output Tokens", _format_tokens(usage.output_tokens))
    table.add_row("Total Tokens", _format_tokens(usage.total_tokens))

    # Cost section
    if usage.total_cost is not None:
        table.add_row("", "")  # Empty line
        table.add_row(Text("Cost", style="bold"), "")
        table.add_row("Input Cost", _format_cost(usage.input_cost))
        if usage.cache_read_cost is not None and usage.cache_read_cost > 0:
            table.add_row("Cache Read Cost", _format_cost(usage.cache_read_cost))
        table.add_row("Output Cost", _format_cost(usage.output_cost))
        table.add_row("Total Cost", _format_cost(usage.total_cost))

    return Padding.indent(table, level=2)
