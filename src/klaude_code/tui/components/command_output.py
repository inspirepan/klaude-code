from rich.console import Group, RenderableType
from rich.table import Table
from rich.text import Text
from rich.tree import Tree

from klaude_code.protocol import events
from klaude_code.protocol.models import SessionIdUIExtra, TaskMetadata
from klaude_code.session import Session
from klaude_code.tui.components.common import truncate_middle
from klaude_code.tui.components.metadata import render_metadata_content
from klaude_code.tui.components.rich.theme import ThemeKey
from klaude_code.tui.workspace import active_work_dir


def render_notice(e: events.NoticeEvent) -> RenderableType:
    """Render a generic notice event."""
    if isinstance(e.ui_extra, SessionIdUIExtra):
        return _render_fork_session_output(e)
    content = e.content or "(no content)"
    style: str = e.style if e.style else (ThemeKey.ERROR if e.is_error else ThemeKey.COMMAND_OUTPUT)
    return truncate_middle(content, base_style=style)


def render_session_stats(e: events.SessionStatsEvent) -> RenderableType:
    """Render settled session usage without assigning costs to user tasks."""
    stats = e.stats
    costs: dict[str, float] = {}
    usages = [meta.usage for meta in stats.by_model] if stats.by_model else [stats.usage]
    for usage in usages:
        if usage is not None and usage.total_cost is not None:
            costs[usage.currency] = costs.get(usage.currency, 0.0) + usage.total_cost

    total = Text("Total cost  ", style=ThemeKey.SESSION_STATUS)
    total.append(
        " + ".join(f"{currency} {cost:.4f}" for currency, cost in costs.items()) or "unavailable",
        style=ThemeKey.SESSION_STATUS_BOLD,
    )
    messages = Text(
        f"Messages  {stats.user_messages_count:,} user · {stats.assistant_messages_count:,} assistant\n"
        f"Tools     {stats.tool_calls_count:,} calls · {stats.tool_results_count:,} results",
        style=ThemeKey.SESSION_STATUS,
    )
    tree = Tree(Text("Usage", style=ThemeKey.SESSION_STATUS_BOLD), guide_style=ThemeKey.METADATA_DIM)
    legacy_metadata = stats.by_model
    if not legacy_metadata and (stats.usage.total_tokens or stats.usage.total_cost is not None):
        legacy_metadata = [TaskMetadata(model_name="All agents", usage=stats.usage)]
    if stats.main_agent_by_model or stats.sub_agent_runs or not legacy_metadata:
        main = tree.add(Text("Main agent", style=ThemeKey.SESSION_STATUS))
        for meta in stats.main_agent_by_model:
            main.add(render_metadata_content(meta, show_context_and_time=False))
        if not stats.main_agent_by_model:
            main.add(Text("No settled usage", style=ThemeKey.METADATA_DIM))
        children = tree.add(Text(f"Sub-agents · {len(stats.sub_agent_runs)} runs", style=ThemeKey.SESSION_STATUS))
        for meta in stats.sub_agent_runs:
            content = render_metadata_content(meta)
            if meta.usage is None:
                content = Group(content, Text("Usage unavailable", style=ThemeKey.METADATA_DIM))
            children.add(content)
        if not stats.sub_agent_runs:
            children.add(Text("No settled runs", style=ThemeKey.METADATA_DIM))
    else:
        legacy = tree.add(Text("Agent attribution unavailable (legacy)", style=ThemeKey.METADATA_DIM))
        for meta in legacy_metadata:
            legacy.add(render_metadata_content(meta, show_context_and_time=False))

    return Group(
        Text("Session status", style=ThemeKey.SESSION_STATUS_BOLD),
        total,
        Text("Settled usage only; running usage excluded.", style=ThemeKey.METADATA_DIM),
        Text(),
        messages,
        Text(),
        tree,
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
