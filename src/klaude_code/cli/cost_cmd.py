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

    def add_usage(self, usage: model.Usage) -> None:
        self.input_tokens += usage.input_tokens
        self.output_tokens += usage.output_tokens
        self.cached_tokens += usage.cached_tokens
        if usage.total_cost is not None:
            if usage.currency == "CNY":
                self.cost_cny += usage.total_cost
            else:
                self.cost_usd += usage.total_cost


@dataclass
class DailyStats:
    """Aggregated stats for a single day."""

    date: str
    by_model: dict[str, ModelUsageStats] = field(default_factory=lambda: dict[str, ModelUsageStats]())

    def add_task_metadata(self, meta: model.TaskMetadata, date_str: str) -> None:
        """Add a TaskMetadata to this day's stats."""
        del date_str  # unused, date is already set
        if not meta.usage or not meta.model_name:
            return

        model_key = meta.model_name
        provider = meta.provider or meta.usage.provider or ""
        if model_key not in self.by_model:
            self.by_model[model_key] = ModelUsageStats(model_name=model_key, provider=provider)
        elif not self.by_model[model_key].provider and provider:
            self.by_model[model_key].provider = provider

        self.by_model[model_key].add_usage(meta.usage)

    def get_subtotal(self) -> ModelUsageStats:
        """Get subtotal across all models for this day."""
        subtotal = ModelUsageStats(model_name="(subtotal)")
        for stats in self.by_model.values():
            subtotal.input_tokens += stats.input_tokens
            subtotal.output_tokens += stats.output_tokens
            subtotal.cached_tokens += stats.cached_tokens
            subtotal.cost_usd += stats.cost_usd
            subtotal.cost_cny += stats.cost_cny
        return subtotal


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
    table.add_column("Output", justify="right")
    table.add_column("Cache", justify="right")
    table.add_column("Total", justify="right")
    table.add_column("USD", justify="right")
    table.add_column("CNY", justify="right")

    # Sort dates
    sorted_dates = sorted(daily_stats.keys())

    # Track global totals by (model, provider)
    global_by_model: dict[tuple[str, str], ModelUsageStats] = {}

    def sort_by_cost(stats: ModelUsageStats) -> tuple[float, float]:
        """Sort key: USD desc, then CNY desc."""
        return (-stats.cost_usd, -stats.cost_cny)

    def render_by_provider(
        models: dict[str, ModelUsageStats],
        date_label: str = "",
        show_subtotal: bool = True,
    ) -> None:
        """Render models grouped by provider with tree structure."""
        # Group models by provider
        models_by_provider: dict[str, list[ModelUsageStats]] = {}
        provider_totals: dict[str, ModelUsageStats] = {}
        for stats in models.values():
            provider_key = stats.provider or "(unknown)"
            if provider_key not in models_by_provider:
                models_by_provider[provider_key] = []
                provider_totals[provider_key] = ModelUsageStats(model_name=provider_key, provider=provider_key)
            models_by_provider[provider_key].append(stats)
            provider_totals[provider_key].input_tokens += stats.input_tokens
            provider_totals[provider_key].output_tokens += stats.output_tokens
            provider_totals[provider_key].cached_tokens += stats.cached_tokens
            provider_totals[provider_key].cost_usd += stats.cost_usd
            provider_totals[provider_key].cost_cny += stats.cost_cny

        # Sort providers by cost, and models within each provider by cost
        sorted_providers = sorted(provider_totals.keys(), key=lambda p: sort_by_cost(provider_totals[p]))
        for provider_key in models_by_provider:
            models_by_provider[provider_key].sort(key=sort_by_cost)

        first_row = True
        for provider_key in sorted_providers:
            provider_stats = provider_totals[provider_key]
            provider_models = models_by_provider[provider_key]

            # Provider row (bold)
            usd_str, cny_str = format_cost_dual(provider_stats.cost_usd, provider_stats.cost_cny)
            table.add_row(
                date_label if first_row else "",
                f"[bold]{provider_key}[/bold]",
                f"[bold]{format_tokens(provider_stats.input_tokens)}[/bold]",
                f"[bold]{format_tokens(provider_stats.output_tokens)}[/bold]",
                f"[bold]{format_tokens(provider_stats.cached_tokens)}[/bold]",
                f"[bold]{format_tokens(provider_stats.total_tokens)}[/bold]",
                f"[bold]{usd_str}[/bold]",
                f"[bold]{cny_str}[/bold]",
            )
            first_row = False

            # Model rows with tree prefix
            for i, stats in enumerate(provider_models):
                is_last = i == len(provider_models) - 1
                prefix = " └─ " if is_last else " ├─ "
                usd_str, cny_str = format_cost_dual(stats.cost_usd, stats.cost_cny)
                table.add_row(
                    "",
                    f"[bright_black dim]{prefix}[/bright_black dim]{stats.model_name}",
                    format_tokens(stats.input_tokens),
                    format_tokens(stats.output_tokens),
                    format_tokens(stats.cached_tokens),
                    format_tokens(stats.total_tokens),
                    usd_str,
                    cny_str,
                )

        # Add subtotal row
        if show_subtotal:
            subtotal = ModelUsageStats(model_name="(subtotal)")
            for stats in models.values():
                subtotal.input_tokens += stats.input_tokens
                subtotal.output_tokens += stats.output_tokens
                subtotal.cached_tokens += stats.cached_tokens
                subtotal.cost_usd += stats.cost_usd
                subtotal.cost_cny += stats.cost_cny
            usd_str, cny_str = format_cost_dual(subtotal.cost_usd, subtotal.cost_cny)
            table.add_row(
                "",
                "[bold](subtotal)[/bold]",
                f"[bold]{format_tokens(subtotal.input_tokens)}[/bold]",
                f"[bold]{format_tokens(subtotal.output_tokens)}[/bold]",
                f"[bold]{format_tokens(subtotal.cached_tokens)}[/bold]",
                f"[bold]{format_tokens(subtotal.total_tokens)}[/bold]",
                f"[bold]{usd_str}[/bold]",
                f"[bold]{cny_str}[/bold]",
            )

    for date_str in sorted_dates:
        day = daily_stats[date_str]

        # Accumulate to global totals by (model, provider)
        for model_name, stats in day.by_model.items():
            model_key = (model_name, stats.provider or "")
            if model_key not in global_by_model:
                global_by_model[model_key] = ModelUsageStats(model_name=model_name, provider=stats.provider)
            global_by_model[model_key].input_tokens += stats.input_tokens
            global_by_model[model_key].output_tokens += stats.output_tokens
            global_by_model[model_key].cached_tokens += stats.cached_tokens
            global_by_model[model_key].cost_usd += stats.cost_usd
            global_by_model[model_key].cost_cny += stats.cost_cny

        # Render this day's data grouped by provider
        render_by_provider(day.by_model, date_label=format_date_display(date_str))

        # Add separator between days
        if date_str != sorted_dates[-1]:
            table.add_section()

    # Add final section for totals
    table.add_section()

    # Build date range label for Total
    if sorted_dates:
        first_date = format_date_display(sorted_dates[0])
        last_date = format_date_display(sorted_dates[-1])
        if first_date == last_date:
            total_label = f"[bold]Total[/bold]\n[dim]{first_date}[/dim]"
        else:
            total_label = f"[bold]Total[/bold]\n[dim]{first_date} ~[/dim]\n[dim]{last_date}[/dim]"
    else:
        total_label = "[bold]Total[/bold]"

    # Group models by provider
    models_by_provider: dict[str, list[ModelUsageStats]] = {}
    provider_totals: dict[str, ModelUsageStats] = {}
    for stats in global_by_model.values():
        provider_key = stats.provider or "(unknown)"
        if provider_key not in models_by_provider:
            models_by_provider[provider_key] = []
            provider_totals[provider_key] = ModelUsageStats(model_name=provider_key, provider=provider_key)
        models_by_provider[provider_key].append(stats)
        provider_totals[provider_key].input_tokens += stats.input_tokens
        provider_totals[provider_key].output_tokens += stats.output_tokens
        provider_totals[provider_key].cached_tokens += stats.cached_tokens
        provider_totals[provider_key].cost_usd += stats.cost_usd
        provider_totals[provider_key].cost_cny += stats.cost_cny

    # Sort providers by cost, and models within each provider by cost
    sorted_providers = sorted(provider_totals.keys(), key=lambda p: sort_by_cost(provider_totals[p]))
    for provider_key in models_by_provider:
        models_by_provider[provider_key].sort(key=sort_by_cost)

    # Add total label row
    table.add_row(total_label, "", "", "", "", "", "", "")

    # Render each provider with its models
    for provider_key in sorted_providers:
        provider_stats = provider_totals[provider_key]
        models = models_by_provider[provider_key]

        # Provider row (bold)
        usd_str, cny_str = format_cost_dual(provider_stats.cost_usd, provider_stats.cost_cny)
        table.add_row(
            "",
            f"[bold]{provider_key}[/bold]",
            f"[bold]{format_tokens(provider_stats.input_tokens)}[/bold]",
            f"[bold]{format_tokens(provider_stats.output_tokens)}[/bold]",
            f"[bold]{format_tokens(provider_stats.cached_tokens)}[/bold]",
            f"[bold]{format_tokens(provider_stats.total_tokens)}[/bold]",
            f"[bold]{usd_str}[/bold]",
            f"[bold]{cny_str}[/bold]",
        )

        # Model rows with tree prefix
        for i, stats in enumerate(models):
            is_last = i == len(models) - 1
            prefix = " └─ " if is_last else " ├─ "
            usd_str, cny_str = format_cost_dual(stats.cost_usd, stats.cost_cny)
            table.add_row(
                "",
                f"[bright_black dim]{prefix}[/bright_black dim]{stats.model_name}",
                format_tokens(stats.input_tokens),
                format_tokens(stats.output_tokens),
                format_tokens(stats.cached_tokens),
                format_tokens(stats.total_tokens),
                usd_str,
                cny_str,
            )

    # Add grand total row
    grand_total = ModelUsageStats(model_name="(total)")
    for stats in global_by_model.values():
        grand_total.input_tokens += stats.input_tokens
        grand_total.output_tokens += stats.output_tokens
        grand_total.cached_tokens += stats.cached_tokens
        grand_total.cost_usd += stats.cost_usd
        grand_total.cost_cny += stats.cost_cny

    usd_str, cny_str = format_cost_dual(grand_total.cost_usd, grand_total.cost_cny)
    table.add_row(
        "",
        "[bold](total)[/bold]",
        f"[bold]{format_tokens(grand_total.input_tokens)}[/bold]",
        f"[bold]{format_tokens(grand_total.output_tokens)}[/bold]",
        f"[bold]{format_tokens(grand_total.cached_tokens)}[/bold]",
        f"[bold]{format_tokens(grand_total.total_tokens)}[/bold]",
        f"[bold]{usd_str}[/bold]",
        f"[bold]{cny_str}[/bold]",
    )

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
