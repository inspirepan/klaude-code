from rich.console import Group, RenderableType
from rich.padding import Padding
from rich.text import Text

from codex_mini.protocol import events
from codex_mini.protocol.commands import CommandName
from codex_mini.ui.renderers import diffs as r_diffs
from codex_mini.ui.renderers.common import create_grid, truncate_display
from codex_mini.ui.renderers.tools import render_path
from codex_mini.ui.base.theme import ThemeKey


def render_developer_message(e: events.DeveloperMessageEvent) -> RenderableType:
    """Render developer message details into a single group.

    Includes: memory paths, external file changes, todo reminder, @file operations.
    Command output is excluded; render it separately via `render_command_output`.
    """
    parts: list[RenderableType] = []

    if mp := e.item.memory_paths:
        grid = create_grid()
        grid.add_row(
            Text("  ⎿ ", style=ThemeKey.REMINDER_BOLD),
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
                Text("  ⎿ ", style=ThemeKey.REMINDER_BOLD),
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
            Text("  ⎿ ", style=ThemeKey.REMINDER_BOLD), Text("Todo hasn't been updated recently", ThemeKey.REMINDER)
        )
        parts.append(grid)

    if e.item.at_files:
        grid = create_grid()
        for at_file in e.item.at_files:
            grid.add_row(
                Text("  ⎿ ", style=ThemeKey.REMINDER_BOLD),
                Text.assemble(
                    (f"{at_file.operation} ", ThemeKey.REMINDER), render_path(at_file.path, ThemeKey.REMINDER_BOLD)
                ),
            )
        parts.append(grid)

    return Group(*parts) if parts else Text("")


def render_command_output(e: events.DeveloperMessageEvent) -> RenderableType:
    """Render developer command output content."""
    if not e.item.command_output:
        return Text("")

    match e.item.command_output.command_name:
        case CommandName.DIFF:
            if e.item.content is None or len(e.item.content) == 0:
                return Padding.indent(Text("(no changes)", style=ThemeKey.TOOL_RESULT), level=2)
            return r_diffs.render_diff_panel(e.item.content, show_file_name=True)
        case CommandName.HELP:
            return Padding.indent(Text.from_markup(e.item.content or ""), level=2)
        case CommandName.PLAN:
            grid = create_grid()
            if e.item.content is not None and len(e.item.content) > 0:
                grid.add_row(Text(" "), Text(e.item.content, style=ThemeKey.TOOL_RESULT))
            if e.item.command_output.ui_extra is not None and len(e.item.command_output.ui_extra) > 0:
                grid.add_row(
                    Text("↓", style=ThemeKey.METADATA),
                    Text("plan with ", style=ThemeKey.METADATA).append_text(
                        Text(e.item.command_output.ui_extra or "N/A", style=ThemeKey.METADATA_BOLD)
                    ),
                )
            return grid
        case _:
            content = e.item.content or "(no content)"
            style = ThemeKey.TOOL_RESULT if not e.item.command_output.is_error else ThemeKey.ERROR
            return Padding.indent(Text(truncate_display(content), style=style), level=2)
