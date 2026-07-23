from dataclasses import dataclass
from typing import ClassVar

from rich.cells import cell_len
from rich.console import Console, ConsoleOptions, Group, RenderableType, RenderResult
from rich.text import Text
from rich.tree import Tree

from klaude_code.config.formatters import format_number
from klaude_code.const import DEFAULT_MAX_TOKENS, LOW_CACHE_HIT_RATE_THRESHOLD
from klaude_code.protocol import events
from klaude_code.protocol.models import TaskMetadata, TaskMetadataItem
from klaude_code.tui.components.common import create_grid, format_elapsed_compact
from klaude_code.tui.components.rich.theme import ThemeKey

METADATA_MIN_DETAILS_WIDTH_FOR_SINGLE_LINE_IDENTITY = 60

# Cell width of tree guide prefixes like "  ├── " (see _RoundedTree.TREE_GUIDES).
TREE_GUIDE_WIDTH = 6
METRIC_COLUMN_GAP = 2
MIN_SUB_AGENTS_FOR_ALIGNMENT = 2


class _RoundedTree(Tree):
    TREE_GUIDES: ClassVar[list[tuple[str, str, str, str]]] = [
        ("      ", "  │   ", "  ├── ", "  ╰── "),
        ("      ", "  │   ", "  ├── ", "  ╰── "),
        ("      ", "  │   ", "  ├── ", "  ╰── "),
    ]


def _should_split_sub_agent_identity(metadata: TaskMetadata, *, max_width: int) -> bool:
    if not metadata.sub_agent_name:
        return False

    name_cells = cell_len(f" {metadata.sub_agent_name} ")
    model_cells = cell_len(metadata.model_name)
    one_line_cells = name_cells + 1 + model_cells
    split_cells = max(name_cells, model_cells)

    if one_line_cells - split_cells < 4:
        return False

    details_width = max_width - one_line_cells
    return details_width <= METADATA_MIN_DETAILS_WIDTH_FOR_SINGLE_LINE_IDENTITY


def _build_identity_text(metadata: TaskMetadata, *, split_sub_agent_and_model: bool) -> Text:
    identity = Text()
    has_description = bool(metadata.description)

    if metadata.sub_agent_name:
        identity.append_text(Text(f" {metadata.sub_agent_name} ", style=ThemeKey.METADATA_SUB_AGENT_NAME))
        if has_description:
            identity.append_text(Text(" ", style=ThemeKey.METADATA))
            identity.append_text(Text(metadata.description or "", style=ThemeKey.METADATA_ITALIC))

        if has_description:
            if split_sub_agent_and_model:
                identity.append_text(Text("\n", style=ThemeKey.METADATA))
                identity.append_text(Text("· ", style=ThemeKey.METADATA_DIM))
            else:
                identity.append_text(Text(" · ", style=ThemeKey.METADATA_DIM))
        elif split_sub_agent_and_model:
            identity.append("\n")
        else:
            identity.append_text(Text(" ", style=ThemeKey.METADATA))
    elif has_description:
        identity.append_text(Text(metadata.description or "", style=ThemeKey.METADATA_ITALIC))
        identity.append_text(Text(" · ", style=ThemeKey.METADATA_DIM))

    identity.append_text(Text(metadata.model_name, style=ThemeKey.METADATA_MODEL))
    if metadata.provider:
        sub_provider = metadata.provider.rsplit("/", 1)[-1] if "/" in metadata.provider else metadata.provider
        identity.append_text(Text(" via ", style=ThemeKey.METADATA_MODEL_DIM))
        identity.append_text(Text(sub_provider, style=ThemeKey.METADATA_MODEL_DIM))
    return identity


class _MetadataContent:
    def __init__(
        self,
        metadata: TaskMetadata,
        *,
        show_context_and_time: bool = True,
        show_step_count: bool = True,
        show_duration: bool = True,
    ) -> None:
        self.metadata = metadata
        self.show_context_and_time = show_context_and_time
        self.show_step_count = show_step_count
        self.show_duration = show_duration

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        max_width = max(1, getattr(options, "max_width", options.size.width))
        identity = _build_identity_text(
            self.metadata,
            split_sub_agent_and_model=_should_split_sub_agent_identity(self.metadata, max_width=max_width),
        )

        content = _build_metadata_content(
            self.metadata,
            identity=identity,
            show_context_and_time=self.show_context_and_time,
            show_step_count=self.show_step_count,
            show_duration=self.show_duration,
        )
        yield content


@dataclass
class _MetricCell:
    """One metric field: a fixed label, a right-alignable value, and an optional suffix."""

    label: str
    value: str
    value_style: str = ThemeKey.METADATA_DIM
    suffix: str = ""
    suffix_style: str = ThemeKey.METADATA_DIM


# Column order shared by the flow-style details line and the aligned layout.
_METRIC_COLUMNS = ["in", "cache", "cache_write", "out", "thought", "ctx", "cost", "time", "tps", "steps"]


def _build_metric_cells(
    metadata: TaskMetadata,
    *,
    show_context_and_time: bool = True,
    show_step_count: bool = True,
    show_duration: bool = True,
) -> dict[str, _MetricCell]:
    """Build metric cells keyed by column name, in _METRIC_COLUMNS order."""
    cells: dict[str, _MetricCell] = {}
    usage = metadata.usage

    if usage is not None:
        input_tokens = max(usage.input_tokens - usage.cached_tokens - usage.cache_write_tokens, 0)
        output_tokens = max(usage.output_tokens - usage.reasoning_tokens, 0)

        cells["in"] = _MetricCell("in", format_number(input_tokens))
        if usage.cached_tokens > 0:
            rate_suffix = ""
            rate_style: str = ThemeKey.METADATA_DIM
            if usage.cache_hit_rate is not None:
                if usage.cache_hit_rate >= 0.995:
                    rate_style = ThemeKey.METADATA_GREEN
                elif usage.cache_hit_rate >= LOW_CACHE_HIT_RATE_THRESHOLD:
                    rate_style = ThemeKey.METADATA_DIM
                else:
                    rate_style = ThemeKey.WARN
                rate_suffix = f" ({usage.cache_hit_rate:.0%})"
            cells["cache"] = _MetricCell(
                "cache", format_number(usage.cached_tokens), suffix=rate_suffix, suffix_style=rate_style
            )
        if usage.cache_write_tokens > 0:
            cells["cache_write"] = _MetricCell("cache write", format_number(usage.cache_write_tokens))
        cells["out"] = _MetricCell("out", format_number(output_tokens))
        if usage.reasoning_tokens > 0:
            cells["thought"] = _MetricCell("thought", format_number(usage.reasoning_tokens))

        if show_context_and_time and usage.context_usage_percent is not None:
            context_size = format_number(usage.context_size or 0)
            effective_limit = (usage.context_limit or 0) - (usage.max_tokens or DEFAULT_MAX_TOKENS)
            effective_limit_str = format_number(effective_limit) if effective_limit > 0 else "?"
            cells["ctx"] = _MetricCell(
                "",
                f"{context_size}/{effective_limit_str}",
                value_style=ThemeKey.METADATA_CONTEXT,
                suffix=f" ({usage.context_usage_percent:.1f}%)",
                suffix_style=ThemeKey.METADATA_CONTEXT,
            )

        if usage.total_cost is not None:
            currency_symbol = "¥" if usage.currency == "CNY" else "$"
            cells["cost"] = _MetricCell("cost", f"{currency_symbol}{usage.total_cost:.4f}")

    if show_duration and show_context_and_time and metadata.task_duration_s is not None:
        cells["time"] = _MetricCell("", format_elapsed_compact(metadata.task_duration_s))

    if usage is not None and usage.throughput_tps is not None:
        cells["tps"] = _MetricCell("", f"{usage.throughput_tps:.1f}", suffix=" tok/s")

    if show_step_count and show_context_and_time and metadata.step_count > 0:
        suffix = " step" if metadata.step_count == 1 else " steps"
        cells["steps"] = _MetricCell("", str(metadata.step_count), suffix=suffix)

    return {key: cells[key] for key in _METRIC_COLUMNS if key in cells}


def _build_details_text(cells: dict[str, _MetricCell]) -> Text | None:
    """Render metric cells as a flow-style ' · '-separated line."""
    if not cells:
        return None

    parts: list[Text] = []
    for cell in cells.values():
        part = Text()
        if cell.label:
            part.append(f"{cell.label} ", style=ThemeKey.METADATA_DIM)
        part.append(cell.value, style=cell.value_style)
        if cell.suffix:
            part.append(cell.suffix, style=cell.suffix_style)
        parts.append(part)
    return Text(" · ", style=ThemeKey.METADATA_DIM).join(parts)


def _build_metadata_content(
    metadata: TaskMetadata,
    *,
    identity: Text,
    show_context_and_time: bool = True,
    show_step_count: bool = True,
    show_duration: bool = True,
) -> RenderableType:
    """Build the content renderable for a single metadata block."""
    details = _build_details_text(
        _build_metric_cells(
            metadata,
            show_context_and_time=show_context_and_time,
            show_step_count=show_step_count,
            show_duration=show_duration,
        )
    )
    if details is None:
        return identity
    return Group(identity, details)


def _build_metadata_content_renderable(
    metadata: TaskMetadata,
    *,
    show_context_and_time: bool = True,
    show_step_count: bool = True,
    show_duration: bool = True,
) -> RenderableType:
    return _MetadataContent(
        metadata,
        show_context_and_time=show_context_and_time,
        show_step_count=show_step_count,
        show_duration=show_duration,
    )


def _build_aligned_metric_line(
    cells: dict[str, _MetricCell],
    *,
    columns: list[str],
    label_widths: dict[str, int],
    value_widths: dict[str, int],
    suffix_widths: dict[str, int],
) -> Text:
    """Render metric cells as one line with columns padded to the shared widths."""
    line = Text()
    for index, column in enumerate(columns):
        if index > 0:
            line.append(" " * METRIC_COLUMN_GAP)
        label_width = label_widths[column]
        cell = cells.get(column)
        if cell is None:
            line.append(" " * (label_width + (1 if label_width else 0) + value_widths[column] + suffix_widths[column]))
            continue
        if label_width:
            line.append(f"{cell.label} ".ljust(label_width + 1), style=ThemeKey.METADATA_DIM)
        value_pad = value_widths[column] - cell_len(cell.value)
        if value_pad > 0:
            line.append(" " * value_pad)
        line.append(cell.value, style=cell.value_style)
        if cell.suffix:
            line.append(cell.suffix, style=cell.suffix_style)
        suffix_pad = suffix_widths[column] - cell_len(cell.suffix)
        if suffix_pad > 0:
            line.append(" " * suffix_pad)
    line.rstrip()
    return line


def _build_aligned_identity_line(metadata: TaskMetadata, *, badge_width: int, description_width: int) -> Text:
    """Render a sub-agent identity line with badge/description columns padded to shared widths."""
    line = Text()
    if badge_width:
        badge = f" {metadata.sub_agent_name} " if metadata.sub_agent_name else ""
        if badge:
            line.append(badge, style=ThemeKey.METADATA_SUB_AGENT_NAME)
        line.append(" " * (badge_width - cell_len(badge) + 1))
    if description_width:
        description = metadata.description or ""
        if description:
            line.append(description, style=ThemeKey.METADATA_ITALIC)
        line.append(" " * (description_width - cell_len(description) + METRIC_COLUMN_GAP))
    line.append(metadata.model_name, style=ThemeKey.METADATA_MODEL)
    if metadata.provider:
        sub_provider = metadata.provider.rsplit("/", 1)[-1] if "/" in metadata.provider else metadata.provider
        line.append(f" via {sub_provider}", style=ThemeKey.METADATA_MODEL_DIM)
    line.rstrip()
    return line


def _build_aligned_sub_agent_rows(
    sub_agents: list[TaskMetadata],
    *,
    max_width: int,
) -> list[RenderableType] | None:
    """Build two-line rows (identity + metrics) with columns aligned across sub-agents.

    Returns None when the aligned metrics line would not fit in max_width.
    """
    all_cells = [_build_metric_cells(meta) for meta in sub_agents]
    columns = [column for column in _METRIC_COLUMNS if any(column in cells for cells in all_cells)]
    if not columns:
        return None

    label_widths: dict[str, int] = {}
    value_widths: dict[str, int] = {}
    suffix_widths: dict[str, int] = {}
    for column in columns:
        column_cells = [cells[column] for cells in all_cells if column in cells]
        label_widths[column] = max(cell_len(cell.label) for cell in column_cells)
        value_widths[column] = max(cell_len(cell.value) for cell in column_cells)
        suffix_widths[column] = max(cell_len(cell.suffix) for cell in column_cells)

    total_width = METRIC_COLUMN_GAP * (len(columns) - 1)
    for column in columns:
        label_width = label_widths[column]
        total_width += label_width + (1 if label_width else 0) + value_widths[column] + suffix_widths[column]
    if total_width + TREE_GUIDE_WIDTH > max_width:
        return None

    badge_width = max(
        (cell_len(f" {meta.sub_agent_name} ") for meta in sub_agents if meta.sub_agent_name),
        default=0,
    )
    description_width = max((cell_len(meta.description or "") for meta in sub_agents), default=0)

    rows: list[RenderableType] = []
    for meta, cells in zip(sub_agents, all_cells, strict=True):
        identity = _build_aligned_identity_line(meta, badge_width=badge_width, description_width=description_width)
        if cells:
            metrics = _build_aligned_metric_line(
                cells,
                columns=columns,
                label_widths=label_widths,
                value_widths=value_widths,
                suffix_widths=suffix_widths,
            )
            rows.append(Group(identity, metrics))
        else:
            rows.append(identity)
    return rows


class _TaskMetadataRenderable:
    """Width-aware renderer for a task metadata block (main agent + sub-agent tree)."""

    def __init__(self, metadata: TaskMetadataItem) -> None:
        self.metadata = metadata

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        max_width = max(1, getattr(options, "max_width", options.size.width))
        main = self.metadata.main_agent
        sub_agents = self.metadata.sub_agent_task_metadata
        main_content = _build_metadata_content_renderable(main)

        grid = create_grid()
        grid.add_row(Text("•", style=ThemeKey.METADATA), main_content)
        if not sub_agents:
            yield grid
            return

        tree = _RoundedTree(grid, guide_style=ThemeKey.METADATA_DIM)

        aligned_rows: list[RenderableType] | None = None
        if len(sub_agents) >= MIN_SUB_AGENTS_FOR_ALIGNMENT:
            aligned_rows = _build_aligned_sub_agent_rows(sub_agents, max_width=max_width)
        if aligned_rows is not None:
            for row in aligned_rows:
                tree.add(row)
        else:
            for meta in sub_agents:
                tree.add(_build_metadata_content_renderable(meta))

        total_cost = 0.0
        currency = "USD"
        if main.usage and main.usage.total_cost:
            total_cost += main.usage.total_cost
            currency = main.usage.currency
        for meta in sub_agents:
            if meta.usage and meta.usage.total_cost:
                total_cost += meta.usage.total_cost

        currency_symbol = "¥" if currency == "CNY" else "$"
        tree.add(
            Text.assemble(
                ("total cost ", ThemeKey.METADATA_DIM),
                (currency_symbol, ThemeKey.METADATA_DIM),
                (f"{total_cost:.4f}", ThemeKey.METADATA_DIM),
            )
        )
        yield tree


def render_task_metadata(e: events.TaskMetadataEvent) -> RenderableType:
    """Render task metadata including main agent and sub-agents."""
    return _TaskMetadataRenderable(e.metadata)
