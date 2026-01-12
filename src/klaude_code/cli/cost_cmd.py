"""Cost command for aggregating usage statistics across all sessions."""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import pydantic
import typer
from rich.box import Box
from rich.console import Console
from rich.table import Table

from klaude_code.protocol import model
from klaude_code.session.codec import decode_jsonl_line
from klaude_code.tui.command.status_cmd import format_cost, format_tokens

ASCII_HORIZONAL = Box(" -- \n    \n -- \n    \n -- \n -- \n    \n -- \n")


@dataclass
class ModelUsageStats:
    """Aggregated usage stats for a single model."""

    model_name: str
    provider: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    cost_usd: float = 0.0
    cost_cny: float = 0.0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    @property
    def non_cached_input_tokens(self) -> int:
        """Non-cached prompt tokens.

        We store `input_tokens` as the provider-reported prompt token count, which
        includes cached tokens for providers that support prompt caching.
        """

        return max(0, self.input_tokens - self.cached_tokens)

    def add_usage(self, usage: model.Usage) -> None:
        self.input_tokens += usage.input_tokens
        self.output_tokens += usage.output_tokens
        self.cached_tokens += usage.cached_tokens
        if usage.total_cost is not None:
            if usage.currency == "CNY":
                self.cost_cny += usage.total_cost
            else:
                self.cost_usd += usage.total_cost


ModelKey = tuple[str, str]  # (model_name, provider)


@dataclass
class SubProviderGroup:
    """Group of models under a sub-provider."""

    name: str
    models: list[ModelUsageStats]
    total: ModelUsageStats


@dataclass
class ProviderGroup:
    """Group of models/sub-providers under a top-level provider."""

    name: str
    sub_providers: dict[str, SubProviderGroup]  # empty if no sub-providers
    models: list[ModelUsageStats]  # direct models (when no sub-provider)
    total: ModelUsageStats


def _sort_by_cost(stats: ModelUsageStats) -> tuple[float, float]:
    return (-stats.cost_usd, -stats.cost_cny)


def group_models_by_provider(models: dict[ModelKey, ModelUsageStats]) -> dict[str, ProviderGroup]:
    """Group models by provider with three-level hierarchy.

    Provider strings like "openrouter/Anthropic" are split into:
    - Top-level: "openrouter"
    - Sub-provider: "Anthropic"

    Returns dict of ProviderGroup sorted by cost desc.
    """
    provider_groups: dict[str, ProviderGroup] = {}

    for stats in models.values():
        provider_raw = stats.provider or "(unknown)"

        # Split provider by first "/"
        if "/" in provider_raw:
            parts = provider_raw.split("/", 1)
            top_provider, sub_provider = parts[0], parts[1]
        else:
            top_provider, sub_provider = provider_raw, ""

        # Initialize top-level provider group
        if top_provider not in provider_groups:
            provider_groups[top_provider] = ProviderGroup(
                name=top_provider,
                sub_providers={},
                models=[],
                total=ModelUsageStats(model_name=top_provider),
            )

        group = provider_groups[top_provider]

        # Accumulate to top-level total
        group.total.input_tokens += stats.input_tokens
        group.total.output_tokens += stats.output_tokens
        group.total.cached_tokens += stats.cached_tokens
        group.total.cost_usd += stats.cost_usd
        group.total.cost_cny += stats.cost_cny

        if sub_provider:
            # Has sub-provider, add to sub-provider group
            if sub_provider not in group.sub_providers:
                group.sub_providers[sub_provider] = SubProviderGroup(
                    name=sub_provider,
                    models=[],
                    total=ModelUsageStats(model_name=sub_provider),
                )
            sub_group = group.sub_providers[sub_provider]
            sub_group.models.append(stats)
            sub_group.total.input_tokens += stats.input_tokens
            sub_group.total.output_tokens += stats.output_tokens
            sub_group.total.cached_tokens += stats.cached_tokens
            sub_group.total.cost_usd += stats.cost_usd
            sub_group.total.cost_cny += stats.cost_cny
        else:
            # No sub-provider, add directly to models
            group.models.append(stats)

    # Sort everything by cost
    for group in provider_groups.values():
        group.models.sort(key=_sort_by_cost)
        for sub_group in group.sub_providers.values():
            sub_group.models.sort(key=_sort_by_cost)
        # Sort sub-providers by cost
        group.sub_providers = dict(sorted(group.sub_providers.items(), key=lambda x: _sort_by_cost(x[1].total)))

    # Sort top-level providers by cost
    sorted_groups = dict(sorted(provider_groups.items(), key=lambda x: _sort_by_cost(x[1].total)))

    return sorted_groups


@dataclass
class DailyStats:
    """Aggregated stats for a single day."""

    date: str
    by_model: dict[ModelKey, ModelUsageStats] = field(default_factory=lambda: dict[ModelKey, ModelUsageStats]())

    def add_task_metadata(self, meta: model.TaskMetadata, date_str: str) -> None:
        """Add a TaskMetadata to this day's stats."""
        del date_str  # unused, date is already set
        if not meta.usage or not meta.model_name:
            return

        provider = meta.provider or meta.usage.provider or ""
        model_key: ModelKey = (meta.model_name, provider)

        if model_key not in self.by_model:
            self.by_model[model_key] = ModelUsageStats(model_name=meta.model_name, provider=provider)

        self.by_model[model_key].add_usage(meta.usage)


def iter_all_sessions() -> list[tuple[str, Path]]:
    """Iterate over all sessions across all projects.

    Returns list of (session_id, events_file_path) tuples.
    """
    projects_dir = Path.home() / ".klaude" / "projects"
    if not projects_dir.exists():
        return []

    sessions: list[tuple[str, Path]] = []
    for project_dir in projects_dir.iterdir():
        if not project_dir.is_dir():
            continue
        sessions_dir = project_dir / "sessions"
        if not sessions_dir.exists():
            continue
        for session_dir in sessions_dir.iterdir():
            if not session_dir.is_dir():
                continue
            events_file = session_dir / "events.jsonl"
            meta_file = session_dir / "meta.json"
            # Skip sub-agent sessions by checking meta.json
            if meta_file.exists():
                import json

                try:
                    meta = json.loads(meta_file.read_text(encoding="utf-8"))
                    if meta.get("sub_agent_state") is not None:
                        continue
                except (json.JSONDecodeError, OSError):
                    pass
            if events_file.exists():
                sessions.append((session_dir.name, events_file))

    return sessions


def extract_task_metadata_from_events(events_path: Path) -> list[tuple[str, model.TaskMetadataItem]]:
    """Extract TaskMetadataItem entries from events.jsonl with their dates.

    Returns list of (date_str, TaskMetadataItem) tuples.
    Skips lines that fail pydantic validation.
    """
    results: list[tuple[str, model.TaskMetadataItem]] = []
    try:
        content = events_path.read_text(encoding="utf-8")
    except OSError:
        return results

    for line in content.splitlines():
        try:
            item = decode_jsonl_line(line)
        except pydantic.ValidationError:
            continue
        if isinstance(item, model.TaskMetadataItem):
            date_str = item.created_at.strftime("%Y-%m-%d")
            results.append((date_str, item))

    return results


def aggregate_all_sessions() -> dict[str, DailyStats]:
    """Aggregate usage stats from all sessions, grouped by date.

    Returns dict mapping date string to DailyStats.
    """
    daily_stats: dict[str, DailyStats] = defaultdict(lambda: DailyStats(date=""))

    sessions = iter_all_sessions()
    for _session_id, events_path in sessions:
        metadata_items = extract_task_metadata_from_events(events_path)
        for date_str, metadata_item in metadata_items:
            if daily_stats[date_str].date == "":
                daily_stats[date_str] = DailyStats(date=date_str)

            # Process main agent metadata
            daily_stats[date_str].add_task_metadata(metadata_item.main_agent, date_str)

            # Process sub-agent metadata
            for sub_meta in metadata_item.sub_agent_task_metadata:
                daily_stats[date_str].add_task_metadata(sub_meta, date_str)

    return dict(daily_stats)


def format_cost_dual(cost_usd: float, cost_cny: float) -> tuple[str, str]:
    """Format costs for both currencies."""
    usd_str = format_cost(cost_usd if cost_usd > 0 else None, "USD")
    cny_str = format_cost(cost_cny if cost_cny > 0 else None, "CNY")
    return usd_str, cny_str


def format_date_display(date_str: str) -> str:
    """Format date string YYYY-MM-DD to 'YYYY M-D WEEKDAY' for table display."""
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        weekday = dt.strftime("%a").upper()
        return f"{dt.year} {dt.month}-{dt.day} {weekday}"
    except (ValueError, TypeError):
        return date_str


def render_cost_table(daily_stats: dict[str, DailyStats]) -> Table:
    """Render the cost table using rich."""
    table = Table(
        title="Usage Statistics",
        show_header=True,
        header_style="bold",
        border_style="bright_black dim",
        padding=(0, 1, 0, 1),
        box=ASCII_HORIZONAL,
    )

    table.add_column("Date", style="cyan")
    table.add_column("Model", overflow="ellipsis")
    table.add_column("Input", justify="right")
    table.add_column("Cache", justify="right")
    table.add_column("Output", justify="right")
    table.add_column("Total", justify="right")
    table.add_column("USD", justify="right")
    table.add_column("CNY", justify="right")

    sorted_dates = sorted(daily_stats.keys())
    global_by_model: dict[ModelKey, ModelUsageStats] = {}

    def add_stats_row(stats: ModelUsageStats, date_label: str = "", prefix: str = "", bold: bool = False) -> None:
        """Add a single stats row to the table."""
        usd_str, cny_str = format_cost_dual(stats.cost_usd, stats.cost_cny)
        if prefix:
            model_col = f"[bright_black dim]{prefix}[/bright_black dim]{stats.model_name}"
        elif bold:
            model_col = f"[bold]{stats.model_name}[/bold]"
        else:
            model_col = stats.model_name

        def fmt(val: str) -> str:
            return f"[bold]{val}[/bold]" if bold else val

        table.add_row(
            date_label,
            model_col,
            fmt(format_tokens(stats.non_cached_input_tokens)),
            fmt(format_tokens(stats.cached_tokens)),
            fmt(format_tokens(stats.output_tokens)),
            fmt(format_tokens(stats.total_tokens)),
            fmt(usd_str),
            fmt(cny_str),
        )

    def render_grouped(
        models: dict[ModelKey, ModelUsageStats],
        date_label: str = "",
        show_subtotal: bool = True,
    ) -> None:
        """Render models grouped by provider with three-level tree structure."""
        provider_groups = group_models_by_provider(models)

        first_row = True
        for group in provider_groups.values():
            # Top-level provider
            add_stats_row(group.total, date_label=date_label if first_row else "", bold=True)
            first_row = False

            if group.sub_providers:
                # Has sub-providers: render three-level tree
                sub_list = list(group.sub_providers.values())
                for sub_idx, sub_group in enumerate(sub_list):
                    is_last_sub = sub_idx == len(sub_list) - 1
                    sub_prefix = " ╰─ " if is_last_sub else " ├─ "

                    # Sub-provider row
                    add_stats_row(sub_group.total, prefix=sub_prefix, bold=True)

                    # Models under sub-provider
                    for model_idx, stats in enumerate(sub_group.models):
                        is_last_model = model_idx == len(sub_group.models) - 1
                        # Indent based on whether sub-provider is last
                        if is_last_sub:
                            model_prefix = "     ╰─ " if is_last_model else "     ├─ "
                        else:
                            model_prefix = " │   ╰─ " if is_last_model else " │   ├─ "
                        add_stats_row(stats, prefix=model_prefix)
            else:
                # No sub-providers: render two-level tree (direct models)
                for model_idx, stats in enumerate(group.models):
                    is_last_model = model_idx == len(group.models) - 1
                    model_prefix = " ╰─ " if is_last_model else " ├─ "
                    add_stats_row(stats, prefix=model_prefix)

        if show_subtotal:
            subtotal = ModelUsageStats(model_name="(subtotal)")
            for stats in models.values():
                subtotal.input_tokens += stats.input_tokens
                subtotal.output_tokens += stats.output_tokens
                subtotal.cached_tokens += stats.cached_tokens
                subtotal.cost_usd += stats.cost_usd
                subtotal.cost_cny += stats.cost_cny
            add_stats_row(subtotal, bold=True)

    for date_str in sorted_dates:
        day = daily_stats[date_str]

        # Accumulate to global totals
        for model_key, stats in day.by_model.items():
            if model_key not in global_by_model:
                global_by_model[model_key] = ModelUsageStats(model_name=stats.model_name, provider=stats.provider)
            global_by_model[model_key].input_tokens += stats.input_tokens
            global_by_model[model_key].output_tokens += stats.output_tokens
            global_by_model[model_key].cached_tokens += stats.cached_tokens
            global_by_model[model_key].cost_usd += stats.cost_usd
            global_by_model[model_key].cost_cny += stats.cost_cny

        render_grouped(day.by_model, date_label=format_date_display(date_str))

        if date_str != sorted_dates[-1]:
            table.add_section()

    # Total section
    table.add_section()

    if sorted_dates:
        first_date = format_date_display(sorted_dates[0])
        last_date = format_date_display(sorted_dates[-1])
        if first_date == last_date:
            total_label = f"[bold]Total[/bold]\n[dim]{first_date}[/dim]"
        else:
            total_label = f"[bold]Total[/bold]\n[dim]{first_date} ~[/dim]\n[dim]{last_date}[/dim]"
    else:
        total_label = "[bold]Total[/bold]"

    table.add_row(total_label, "", "", "", "", "", "", "")
    render_grouped(global_by_model, show_subtotal=False)

    # Grand total
    grand_total = ModelUsageStats(model_name="(total)")
    for stats in global_by_model.values():
        grand_total.input_tokens += stats.input_tokens
        grand_total.output_tokens += stats.output_tokens
        grand_total.cached_tokens += stats.cached_tokens
        grand_total.cost_usd += stats.cost_usd
        grand_total.cost_cny += stats.cost_cny
    add_stats_row(grand_total, bold=True)

    return table


def cost_command(
    days: int | None = typer.Option(None, "--days", "-d", help="Limit to last N days"),
) -> None:
    """Show usage stats"""
    daily_stats = aggregate_all_sessions()

    if not daily_stats:
        typer.echo("No usage data found.")
        raise typer.Exit(0)

    # Filter by days if specified
    if days is not None:
        cutoff = datetime.now().strftime("%Y-%m-%d")
        from datetime import timedelta

        cutoff_date = datetime.now() - timedelta(days=days)
        cutoff = cutoff_date.strftime("%Y-%m-%d")
        daily_stats = {k: v for k, v in daily_stats.items() if k >= cutoff}

    if not daily_stats:
        typer.echo(f"No usage data found in the last {days} days.")
        raise typer.Exit(0)

    table = render_cost_table(daily_stats)
    console = Console()
    console.print(table)


def register_cost_commands(app: typer.Typer) -> None:
    """Register cost command to the given Typer app."""
    app.command("cost")(cost_command)
