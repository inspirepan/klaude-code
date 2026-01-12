from rich.console import RenderableType
from rich.table import Table
from rich.text import Text

from klaude_code.protocol import events, model
from klaude_code.session import Session
from klaude_code.tui.components.common import truncate_middle
from klaude_code.tui.components.rich.theme import ThemeKey


def render_command_output(e: events.CommandOutputEvent) -> RenderableType:
    """Render command output content."""
    match e.command_name:
        case "status":
            return _render_status_output(e)
        case "fork-session":
            return _render_fork_session_output(e)
        case _:
            content = e.content or "(no content)"
            style = ThemeKey.TOOL_RESULT if not e.is_error else ThemeKey.ERROR
            return truncate_middle(content, base_style=style)


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
    symbol = "Y" if currency == "CNY" else "$"
    if cost < 0.01:
        return f"{symbol}{cost:.4f}"
    return f"{symbol}{cost:.2f}"


def _render_fork_session_output(e: events.CommandOutputEvent) -> RenderableType:
    """Render fork session output with usage instructions."""
    if not isinstance(e.ui_extra, model.SessionIdUIExtra):
        return Text(e.content, style=ThemeKey.TOOL_RESULT)

    grid = Table.grid(padding=(0, 1))
    session_id = e.ui_extra.session_id
    short_id = Session.shortest_unique_prefix(session_id)
    grid.add_column(style=ThemeKey.TOOL_RESULT, overflow="fold")

    grid.add_row(Text("Session forked. Resume command copied to clipboard:", style=ThemeKey.TOOL_RESULT))
    grid.add_row(Text(f"  klaude -r {short_id}", style=ThemeKey.TOOL_RESULT_BOLD))

    return grid


def _render_status_output(e: events.CommandOutputEvent) -> RenderableType:
    """Render session status with total cost and per-model breakdown."""
    if not isinstance(e.ui_extra, model.SessionStatusUIExtra):
        return Text("(no status data)", style=ThemeKey.TOOL_RESULT)

    status = e.ui_extra
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

    return table
