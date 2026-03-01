from typing import ClassVar

from rich.cells import cell_len
from rich.console import Console, ConsoleOptions, Group, RenderableType, RenderResult
from rich.text import Text
from rich.tree import Tree

from klaude_code.const import DEFAULT_MAX_TOKENS, LOW_CACHE_HIT_RATE_THRESHOLD
from klaude_code.protocol import events, model
from klaude_code.tui.components.common import create_grid, format_elapsed_compact
from klaude_code.tui.components.rich.theme import ThemeKey
from klaude_code.ui.common import format_number

WORKED_LINE_DURATION_THRESHOLD_S = 60
WORKED_LINE_TURN_COUNT_THRESHOLD = 4
METADATA_MIN_DETAILS_WIDTH_FOR_SINGLE_LINE_IDENTITY = 60


class _RoundedTree(Tree):
    TREE_GUIDES: ClassVar[list[tuple[str, str, str, str]]] = [
        ("      ", "  │   ", "  ├── ", "  ╰── "),
        ("      ", "  │   ", "  ├── ", "  ╰── "),
        ("      ", "  │   ", "  ├── ", "  ╰── "),
    ]


def _should_split_sub_agent_identity(metadata: model.TaskMetadata, *, max_width: int) -> bool:
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


def _build_identity_text(metadata: model.TaskMetadata, *, split_sub_agent_and_model: bool) -> Text:
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

    identity.append_text(Text(metadata.model_name, style=ThemeKey.METADATA))
    if metadata.provider:
        sub_provider = metadata.provider.rsplit("/", 1)[-1] if "/" in metadata.provider else metadata.provider
        identity.append_text(Text(" via ", style=ThemeKey.METADATA_DIM))
        identity.append_text(Text(sub_provider, style=ThemeKey.METADATA_DIM))
    return identity


class _MetadataContent:
    def __init__(
        self,
        metadata: model.TaskMetadata,
        *,
        show_context_and_time: bool = True,
        show_turn_count: bool = True,
        show_duration: bool = True,
    ) -> None:
        self.metadata = metadata
        self.show_context_and_time = show_context_and_time
        self.show_turn_count = show_turn_count
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
            show_turn_count=self.show_turn_count,
            show_duration=self.show_duration,
        )
        yield content


def _build_metadata_content(
    metadata: model.TaskMetadata,
    *,
    identity: Text,
    show_context_and_time: bool = True,
    show_turn_count: bool = True,
    show_duration: bool = True,
) -> RenderableType:
    """Build the content renderable for a single metadata block."""
    currency = metadata.usage.currency if metadata.usage else "USD"
    currency_symbol = "¥" if currency == "CNY" else "$"

    parts: list[Text] = []

    if metadata.usage is not None:
        input_tokens = max(metadata.usage.input_tokens - metadata.usage.cached_tokens, 0)
        output_tokens = max(metadata.usage.output_tokens - metadata.usage.reasoning_tokens, 0)

        parts.append(
            Text.assemble(
                ("in ", ThemeKey.METADATA),
                (format_number(input_tokens), ThemeKey.METADATA),
            )
        )
        if metadata.usage.cached_tokens > 0:
            cache_text = Text.assemble(
                ("cache ", ThemeKey.METADATA),
                (format_number(metadata.usage.cached_tokens), ThemeKey.METADATA),
            )
            if metadata.usage.cache_hit_rate is not None:
                if metadata.usage.cache_hit_rate >= 0.995:
                    rate_style = ThemeKey.METADATA_GREEN
                elif metadata.usage.cache_hit_rate >= LOW_CACHE_HIT_RATE_THRESHOLD:
                    rate_style = ThemeKey.METADATA
                else:
                    rate_style = ThemeKey.WARN
                cache_text.append(f" ({metadata.usage.cache_hit_rate:.0%})", style=rate_style)
            parts.append(cache_text)
        parts.append(
            Text.assemble(
                ("out ", ThemeKey.METADATA),
                (format_number(output_tokens), ThemeKey.METADATA),
            )
        )
        if metadata.usage.reasoning_tokens > 0:
            parts.append(
                Text.assemble(
                    ("thought ", ThemeKey.METADATA),
                    (format_number(metadata.usage.reasoning_tokens), ThemeKey.METADATA),
                )
            )

        if show_context_and_time and metadata.usage.context_usage_percent is not None:
            context_size = format_number(metadata.usage.context_size or 0)
            effective_limit = (metadata.usage.context_limit or 0) - (metadata.usage.max_tokens or DEFAULT_MAX_TOKENS)
            effective_limit_str = format_number(effective_limit) if effective_limit > 0 else "?"
            parts.append(
                Text.assemble(
                    (context_size, ThemeKey.METADATA_CONTEXT),
                    ("/", ThemeKey.METADATA_CONTEXT),
                    (effective_limit_str, ThemeKey.METADATA_CONTEXT),
                    (f" ({metadata.usage.context_usage_percent:.1f}%)", ThemeKey.METADATA_CONTEXT),
                )
            )

        if metadata.usage.total_cost is not None:
            parts.append(
                Text.assemble(
                    ("cost ", ThemeKey.METADATA),
                    (currency_symbol, ThemeKey.METADATA),
                    (f"{metadata.usage.total_cost:.4f}", ThemeKey.METADATA),
                )
            )

    if show_duration and show_context_and_time and metadata.task_duration_s is not None:
        parts.append(Text(format_elapsed_compact(metadata.task_duration_s), style=ThemeKey.METADATA))

    if metadata.usage is not None and metadata.usage.throughput_tps is not None:
        parts.append(
            Text.assemble(
                (f"{metadata.usage.throughput_tps:.1f}", ThemeKey.METADATA),
                (" tok/s", ThemeKey.METADATA),
            )
        )

    if show_turn_count and show_context_and_time and metadata.turn_count > 0:
        suffix = " step" if metadata.turn_count == 1 else " steps"
        parts.append(
            Text.assemble(
                (str(metadata.turn_count), ThemeKey.METADATA),
                (suffix, ThemeKey.METADATA),
            )
        )

    if not parts:
        return identity

    details = Text(" · ", style=ThemeKey.METADATA_DIM).join(parts)
    return Group(identity, details)


def _build_metadata_content_renderable(
    metadata: model.TaskMetadata,
    *,
    show_context_and_time: bool = True,
    show_turn_count: bool = True,
    show_duration: bool = True,
) -> RenderableType:
    return _MetadataContent(
        metadata,
        show_context_and_time=show_context_and_time,
        show_turn_count=show_turn_count,
        show_duration=show_duration,
    )


def render_task_metadata(e: events.TaskMetadataEvent) -> RenderableType:
    """Render task metadata including main agent and sub-agents."""
    renderables: list[RenderableType] = []

    # "Worked for Xs, N steps" line
    main = e.metadata.main_agent
    duration_s = main.task_duration_s
    should_show_worked_line = duration_s is not None and (
        duration_s > WORKED_LINE_DURATION_THRESHOLD_S or main.turn_count > WORKED_LINE_TURN_COUNT_THRESHOLD
    )
    if should_show_worked_line and duration_s is not None:
        parts: list[tuple[str, ThemeKey]] = [
            ("✔ ", ThemeKey.METADATA_GREEN),
            ("Worked for ", ThemeKey.METADATA_GREEN),
            (format_elapsed_compact(duration_s), ThemeKey.METADATA_GREEN),
        ]
        if main.turn_count > 0:
            suffix = "step" if main.turn_count == 1 else "steps"
            parts.append((f" in {main.turn_count} {suffix}", ThemeKey.METADATA_GREEN_DIM))
        renderables.append(Text.assemble(*parts))
        renderables.append(Text(""))

    has_sub_agents = len(e.metadata.sub_agent_task_metadata) > 0
    main_content = _build_metadata_content_renderable(
        main,
        show_context_and_time=True,
        show_turn_count=not should_show_worked_line,
        show_duration=not should_show_worked_line,
    )

    if has_sub_agents:
        root_grid = create_grid()
        root_grid.add_row(Text("•", style=ThemeKey.METADATA), main_content)
        tree = _RoundedTree(root_grid, guide_style=ThemeKey.METADATA_DIM)

        for meta in e.metadata.sub_agent_task_metadata:
            tree.add(_build_metadata_content_renderable(meta, show_context_and_time=True))

        # Total cost
        total_cost = 0.0
        currency = "USD"
        if main.usage and main.usage.total_cost:
            total_cost += main.usage.total_cost
            currency = main.usage.currency
        for meta in e.metadata.sub_agent_task_metadata:
            if meta.usage and meta.usage.total_cost:
                total_cost += meta.usage.total_cost

        currency_symbol = "¥" if currency == "CNY" else "$"
        tree.add(
            Text.assemble(
                ("total cost ", ThemeKey.METADATA),
                (currency_symbol, ThemeKey.METADATA),
                (f"{total_cost:.4f}", ThemeKey.METADATA),
            )
        )
        renderables.append(tree)
    else:
        grid = create_grid()
        grid.add_row(Text("•", style=ThemeKey.METADATA), main_content)
        renderables.append(grid)

    return Group(*renderables)
