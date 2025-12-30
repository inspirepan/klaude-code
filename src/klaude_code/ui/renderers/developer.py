from rich.console import Group, RenderableType
from rich.padding import Padding
from rich.table import Table
from rich.text import Text

from klaude_code.protocol import commands, events, model
from klaude_code.ui.renderers.common import create_grid, truncate_display
from klaude_code.ui.renderers.tools import render_path
from klaude_code.ui.rich.markdown import NoInsetMarkdown
from klaude_code.ui.rich.theme import ThemeKey

REMINDER_BULLET = "  ⧉"


def need_render_developer_message(e: events.DeveloperMessageEvent) -> bool:
    return bool(
        e.item.memory_paths
        or e.item.external_file_changes
        or e.item.todo_use
        or e.item.at_files
        or e.item.user_image_count
        or e.item.skill_name
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
            Text(REMINDER_BULLET, style=ThemeKey.REMINDER),
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
                Text(REMINDER_BULLET, style=ThemeKey.REMINDER),
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
            Text(REMINDER_BULLET, style=ThemeKey.REMINDER),
            Text("Todo hasn't been updated recently", ThemeKey.REMINDER),
        )
        parts.append(grid)

    if e.item.at_files:
        grid = create_grid()
        # Group at_files by (operation, mentioned_in)
        grouped: dict[tuple[str, str | None], list[str]] = {}
        for at_file in e.item.at_files:
            key = (at_file.operation, at_file.mentioned_in)
            if key not in grouped:
                grouped[key] = []
            grouped[key].append(at_file.path)

        for (operation, mentioned_in), paths in grouped.items():
            path_texts = Text(", ", ThemeKey.REMINDER).join(render_path(p, ThemeKey.REMINDER_BOLD) for p in paths)
            if mentioned_in:
                grid.add_row(
                    Text(REMINDER_BULLET, style=ThemeKey.REMINDER),
                    Text.assemble(
                        (f"{operation} ", ThemeKey.REMINDER),
                        path_texts,
                        (" mentioned in ", ThemeKey.REMINDER),
                        render_path(mentioned_in, ThemeKey.REMINDER_BOLD),
                    ),
                )
            else:
                grid.add_row(
                    Text(REMINDER_BULLET, style=ThemeKey.REMINDER),
                    Text.assemble(
                        (f"{operation} ", ThemeKey.REMINDER),
                        path_texts,
                    ),
                )
        parts.append(grid)

    if uic := e.item.user_image_count:
        grid = create_grid()
        grid.add_row(
            Text(REMINDER_BULLET, style=ThemeKey.REMINDER),
            Text(f"Attached {uic} image{'s' if uic > 1 else ''}", style=ThemeKey.REMINDER),
        )
        parts.append(grid)

    if sn := e.item.skill_name:
        grid = create_grid()
        grid.add_row(
            Text(REMINDER_BULLET, style=ThemeKey.REMINDER),
            Text.assemble(
                ("Activated skill ", ThemeKey.REMINDER),
                (sn, ThemeKey.REMINDER_BOLD),
            ),
        )
        parts.append(grid)

    return Group(*parts) if parts else Text("")


def render_command_output(e: events.DeveloperMessageEvent) -> RenderableType:
    """Render developer command output content."""
    if not e.item.command_output:
        return Text("")

    match e.item.command_output.command_name:
        case commands.CommandName.HELP:
            return Padding.indent(Text.from_markup(e.item.content or ""), level=2)
        case commands.CommandName.STATUS:
            return _render_status_output(e.item.command_output)
        case commands.CommandName.RELEASE_NOTES:
            return Padding.indent(NoInsetMarkdown(e.item.content or ""), level=2)
        case commands.CommandName.FORK_SESSION:
            return _render_fork_session_output(e.item.command_output)
        case _:
            content = e.item.content or "(no content)"
            style = ThemeKey.TOOL_RESULT if not e.item.command_output.is_error else ThemeKey.ERROR
            return Padding.indent(truncate_display(content, base_style=style), level=2)


def _format_tokens(tokens: int) -> str:
    """Format token count with K/M suffix for readability."""
    if tokens >= 1_000_000:
        return f"{tokens / 1_000_000:.2f}M"
    if tokens >= 1_000:
        return f"{tokens / 1_000:.1f}K"
    return str(tokens)


def _format_cost(cost: float | None, currency: str = "USD") -> str:
    """Format cost with currency symbol."""
    if cost is None:
        return "-"
    symbol = "¥" if currency == "CNY" else "$"
    if cost < 0.01:
        return f"{symbol}{cost:.4f}"
    return f"{symbol}{cost:.2f}"


def _render_fork_session_output(command_output: model.CommandOutput) -> RenderableType:
    """Render fork session output with usage instructions."""
    if not isinstance(command_output.ui_extra, model.SessionIdUIExtra):
        return Padding.indent(Text("(no session id)", style=ThemeKey.METADATA), level=2)

    grid = Table.grid(padding=(0, 1))
    session_id = command_output.ui_extra.session_id
    grid.add_column(style=ThemeKey.METADATA, overflow="fold")

    grid.add_row(Text("Session forked. To continue in a new conversation:", style=ThemeKey.METADATA))
    grid.add_row(Text(f"  klaude --resume-by-id {session_id}", style=ThemeKey.METADATA_BOLD))

    return Padding.indent(grid, level=2)


def _render_status_output(command_output: model.CommandOutput) -> RenderableType:
    """Render session status with total cost and per-model breakdown."""
    if not isinstance(command_output.ui_extra, model.SessionStatusUIExtra):
        return Text("(no status data)", style=ThemeKey.METADATA)

    status = command_output.ui_extra
    usage = status.usage

    table = Table.grid(padding=(0, 2))
    table.add_column(style=ThemeKey.METADATA, overflow="fold")
    table.add_column(style=ThemeKey.METADATA, overflow="fold")

    # Total cost line
    table.add_row(
        Text("Total cost:", style=ThemeKey.METADATA_BOLD),
        Text(_format_cost(usage.total_cost, usage.currency), style=ThemeKey.METADATA_BOLD),
    )

    # Per-model breakdown
    if status.by_model:
        table.add_row(Text("Usage by model:", style=ThemeKey.METADATA_BOLD), "")
        for meta in status.by_model:
            model_label = meta.model_name
            if meta.provider:
                model_label = f"{meta.model_name} ({meta.provider.lower().replace(' ', '-')})"

            if meta.usage:
                usage_detail = (
                    f"{_format_tokens(meta.usage.input_tokens)} input, "
                    f"{_format_tokens(meta.usage.output_tokens)} output, "
                    f"{_format_tokens(meta.usage.cached_tokens)} cache read, "
                    f"{_format_tokens(meta.usage.reasoning_tokens)} thinking, "
                    f"({_format_cost(meta.usage.total_cost, meta.usage.currency)})"
                )
            else:
                usage_detail = "(no usage data)"
            table.add_row(f"{model_label}:", usage_detail)

    return Padding.indent(table, level=2)
