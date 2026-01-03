from rich.console import Group, RenderableType
from rich.padding import Padding
from rich.table import Table
from rich.text import Text

from klaude_code.protocol import commands, events, message, model
from klaude_code.tui.components.common import create_grid, truncate_middle
from klaude_code.tui.components.rich.markdown import NoInsetMarkdown
from klaude_code.tui.components.rich.theme import ThemeKey
from klaude_code.tui.components.tools import render_path

REMINDER_BULLET = "  ⧉"


def get_command_output(item: message.DeveloperMessage) -> model.CommandOutput | None:
    if not item.ui_extra:
        return None
    for ui_item in item.ui_extra.items:
        if isinstance(ui_item, model.CommandOutputUIItem):
            return ui_item.output
    return None


def need_render_developer_message(e: events.DeveloperMessageEvent) -> bool:
    if not e.item.ui_extra:
        return False
    return any(not isinstance(ui_item, model.CommandOutputUIItem) for ui_item in e.item.ui_extra.items)


def render_developer_message(e: events.DeveloperMessageEvent) -> RenderableType:
    """Render developer message details into a single group.

    Includes: memory paths, external file changes, todo reminder, @file operations.
    Command output is excluded; render it separately via `render_command_output`.
    """
    parts: list[RenderableType] = []

    if e.item.ui_extra:
        for ui_item in e.item.ui_extra.items:
            match ui_item:
                case model.MemoryLoadedUIItem() as item:
                    grid = create_grid()
                    grid.add_row(
                        Text(REMINDER_BULLET, style=ThemeKey.REMINDER),
                        Text.assemble(
                            ("Load memory ", ThemeKey.REMINDER),
                            Text(", ", ThemeKey.REMINDER).join(
                                render_path(mem.path, ThemeKey.REMINDER_BOLD) for mem in item.files
                            ),
                        ),
                    )
                    parts.append(grid)
                case model.ExternalFileChangesUIItem() as item:
                    grid = create_grid()
                    for file_path in item.paths:
                        grid.add_row(
                            Text(REMINDER_BULLET, style=ThemeKey.REMINDER),
                            Text.assemble(
                                ("Read ", ThemeKey.REMINDER),
                                render_path(file_path, ThemeKey.REMINDER_BOLD),
                                (" after external changes", ThemeKey.REMINDER),
                            ),
                        )
                    parts.append(grid)
                case model.TodoReminderUIItem() as item:
                    match item.reason:
                        case "not_used_recently":
                            text = "Todo hasn't been updated recently"
                        case "empty":
                            text = "Todo list is empty"
                        case _:
                            text = "Todo reminder"
                    grid = create_grid()
                    grid.add_row(
                        Text(REMINDER_BULLET, style=ThemeKey.REMINDER),
                        Text(text, ThemeKey.REMINDER),
                    )
                    parts.append(grid)
                case model.AtFileOpsUIItem() as item:
                    grid = create_grid()
                    grouped: dict[tuple[str, str | None], list[str]] = {}
                    for op in item.ops:
                        key = (op.operation, op.mentioned_in)
                        grouped.setdefault(key, []).append(op.path)

                    for (operation, mentioned_in), paths in grouped.items():
                        path_texts = Text(", ", ThemeKey.REMINDER).join(
                            render_path(p, ThemeKey.REMINDER_BOLD) for p in paths
                        )
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
                case model.UserImagesUIItem() as item:
                    grid = create_grid()
                    count = item.count
                    grid.add_row(
                        Text(REMINDER_BULLET, style=ThemeKey.REMINDER),
                        Text(
                            f"Attached {count} image{'s' if count > 1 else ''}",
                            style=ThemeKey.REMINDER,
                        ),
                    )
                    parts.append(grid)
                case model.SkillActivatedUIItem() as item:
                    grid = create_grid()
                    grid.add_row(
                        Text(REMINDER_BULLET, style=ThemeKey.REMINDER),
                        Text.assemble(
                            ("Activated skill ", ThemeKey.REMINDER),
                            (item.name, ThemeKey.REMINDER_BOLD),
                        ),
                    )
                    parts.append(grid)
                case model.CommandOutputUIItem():
                    # Rendered via render_command_output
                    pass

    return Group(*parts) if parts else Text("")


def render_command_output(e: events.DeveloperMessageEvent) -> RenderableType:
    """Render developer command output content."""
    command_output = get_command_output(e.item)
    if not command_output:
        return Text("")

    content = message.join_text_parts(e.item.parts)
    match command_output.command_name:
        case commands.CommandName.HELP:
            return Padding.indent(Text.from_markup(content or "", style=ThemeKey.TOOL_RESULT), level=2)
        case commands.CommandName.STATUS:
            return _render_status_output(command_output)
        case commands.CommandName.RELEASE_NOTES:
            return Padding.indent(NoInsetMarkdown(content or ""), level=2)
        case commands.CommandName.FORK_SESSION:
            return _render_fork_session_output(command_output)
        case _:
            content = content or "(no content)"
            style = ThemeKey.TOOL_RESULT if not command_output.is_error else ThemeKey.ERROR
            return Padding.indent(truncate_middle(content, base_style=style), level=2)


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
        return Padding.indent(Text("(no session id)", style=ThemeKey.TOOL_RESULT), level=2)

    grid = Table.grid(padding=(0, 1))
    session_id = command_output.ui_extra.session_id
    grid.add_column(style=ThemeKey.TOOL_RESULT, overflow="fold")

    grid.add_row(Text("Session forked. Resume command copied to clipboard:", style=ThemeKey.TOOL_RESULT))
    grid.add_row(Text(f"  klaude --resume-by-id {session_id}", style=ThemeKey.TOOL_RESULT_BOLD))

    return Padding.indent(grid, level=2)


def _render_status_output(command_output: model.CommandOutput) -> RenderableType:
    """Render session status with total cost and per-model breakdown."""
    if not isinstance(command_output.ui_extra, model.SessionStatusUIExtra):
        return Text("(no status data)", style=ThemeKey.TOOL_RESULT)

    status = command_output.ui_extra
    usage = status.usage

    table = Table.grid(padding=(0, 2))
    table.add_column(style=ThemeKey.TOOL_RESULT, overflow="fold")
    table.add_column(style=ThemeKey.TOOL_RESULT, overflow="fold")

    # Total cost line
    table.add_row(
        Text("Total cost:", style=ThemeKey.TOOL_RESULT_BOLD),
        Text(_format_cost(usage.total_cost, usage.currency), style=ThemeKey.TOOL_RESULT_BOLD),
    )

    # Per-model breakdown
    if status.by_model:
        table.add_row(Text("Usage by model:", style=ThemeKey.TOOL_RESULT_BOLD), "")
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
