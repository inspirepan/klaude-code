from rich.console import Group, RenderableType
from rich.table import Table
from rich.text import Text

from klaude_code.protocol import events
from klaude_code.protocol.models import SessionIdUIExtra, TaskMetadata
from klaude_code.session import Session
from klaude_code.tui.components.common import truncate_middle
from klaude_code.tui.components.metadata import SessionMetadataContent
from klaude_code.tui.components.rich.theme import ThemeKey
from klaude_code.tui.workspace import active_work_dir


def render_notice(e: events.NoticeEvent) -> RenderableType:
    """Render a generic notice event."""
    if isinstance(e.ui_extra, SessionIdUIExtra):
        return _render_fork_session_output(e)
    content = e.content or "(no content)"
    style: str = e.style if e.style else (ThemeKey.ERROR if e.is_error else ThemeKey.COMMAND_OUTPUT)
    return truncate_middle(content, base_style=style)


def _session_cost_summary(metadata: list[TaskMetadata]) -> str:
    costs: dict[str, float] = {}
    unknown = 0
    for meta in metadata:
        usage = meta.usage
        if usage is not None and usage.total_cost is not None:
            costs[usage.currency] = costs.get(usage.currency, 0.0) + usage.total_cost
        else:
            unknown += 1
    result = " + ".join(f"{currency} {cost:.4f}" for currency, cost in sorted(costs.items())) or "unavailable"
    return f"{result} ({unknown} unknown)" if unknown else result


def _session_usage_list(metadata: list[TaskMetadata], *, show_context_and_time: bool = True) -> Table:
    grid = Table.grid(padding=(0, 2))
    grid.add_column(justify="right", style=ThemeKey.SESSION_STATUS, no_wrap=True)
    grid.add_column(ratio=1, overflow="fold")
    for meta in metadata:
        usage = meta.usage
        cost = "—"
        if usage is not None and usage.total_cost is not None:
            symbol = {"USD": "$", "CNY": "¥"}.get(usage.currency, f"{usage.currency} ")
            cost = f"{symbol}{usage.total_cost:.4f}"
        grid.add_row(cost, SessionMetadataContent(meta, show_context_and_time=show_context_and_time))
    return grid


def render_session_stats(e: events.SessionStatsEvent) -> RenderableType:
    """Render settled session costs first, retaining all available usage metrics."""
    stats = e.stats
    legacy_metadata = stats.by_model
    if not legacy_metadata and (stats.usage.total_tokens or stats.usage.total_cost is not None):
        legacy_metadata = [TaskMetadata(model_name="All agents", usage=stats.usage)]
    attributed = bool(stats.main_agent_by_model or stats.sub_agent_runs or not legacy_metadata)
    total_metadata = [*stats.main_agent_by_model, *stats.sub_agent_runs] if attributed else legacy_metadata
    total = Text("Total cost  ", style=ThemeKey.SESSION_STATUS)
    total.append(_session_cost_summary(total_metadata), style=ThemeKey.SESSION_STATUS)
    messages = Text(
        f"Messages  {stats.user_messages_count:,} user · {stats.assistant_messages_count:,} assistant\n"
        f"Tools     {stats.tool_calls_count:,} calls · {stats.tool_results_count:,} results",
        style=ThemeKey.SESSION_STATUS,
    )
    if attributed:
        # Currency groups avoid comparing nominal costs across currencies.
        runs = sorted(
            stats.sub_agent_runs,
            key=lambda meta: (
                meta.usage is None or meta.usage.total_cost is None,
                meta.usage.currency if meta.usage is not None else "",
                -(meta.usage.total_cost or 0.0) if meta.usage is not None else 0.0,
            ),
        )
        usage_content = Group(
            Text(f"Main agent · {_session_cost_summary(stats.main_agent_by_model)}", style=ThemeKey.SESSION_STATUS),
            _session_usage_list(stats.main_agent_by_model)
            if stats.main_agent_by_model
            else Text("No settled usage", style=ThemeKey.METADATA_DIM),
            Text(),
            Text(
                f"Sub-agents · {len(runs)} runs · {_session_cost_summary(runs)} · cost descending per currency",
                style=ThemeKey.SESSION_STATUS,
            ),
            _session_usage_list(runs) if runs else Text("No settled runs", style=ThemeKey.METADATA_DIM),
        )
    else:
        usage_content = Group(
            Text("Agent attribution unavailable (legacy)", style=ThemeKey.METADATA_DIM),
            _session_usage_list(legacy_metadata, show_context_and_time=False),
        )

    return Group(
        Text("Session status", style=ThemeKey.SESSION_STATUS),
        total,
        Text("Settled usage only; running usage excluded.", style=ThemeKey.METADATA_DIM),
        Text(),
        messages,
        Text(),
        usage_content,
        Text(),
        Text(f"Session  {stats.session_id}", style=ThemeKey.METADATA_DIM, no_wrap=True, overflow="ellipsis"),
        Text(f"Events   {stats.events_file_path}", style=ThemeKey.METADATA_DIM, no_wrap=True, overflow="ellipsis"),
    )


def _render_fork_session_output(e: events.NoticeEvent) -> RenderableType:
    if not isinstance(e.ui_extra, SessionIdUIExtra):
        return Text(e.content, style=ThemeKey.TOOL_RESULT)

    grid = Table.grid(padding=(0, 1))
    session_id = e.ui_extra.session_id
    short_id = Session.shortest_unique_prefix(session_id, work_dir=active_work_dir())
    grid.add_column(style=ThemeKey.TOOL_RESULT, overflow="fold")

    grid.add_row(Text("Session forked. Resume command copied to clipboard:", style=ThemeKey.TOOL_RESULT))
    grid.add_row(Text(f"  klaude -r {short_id}", style=ThemeKey.TOOL_RESULT_BOLD))

    return grid
