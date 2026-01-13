from rich.console import Group, RenderableType
from rich.text import Text

from klaude_code.const import DEFAULT_MAX_TOKENS
from klaude_code.protocol import events, model
from klaude_code.tui.components.common import create_grid
from klaude_code.tui.components.rich.theme import ThemeKey
from klaude_code.ui.common import format_number


def _render_task_metadata_block(
    metadata: model.TaskMetadata,
    *,
    mark: Text,
    show_context_and_time: bool = True,
) -> RenderableType:
    """Render a single TaskMetadata block.

    Args:
        metadata: The TaskMetadata to render.
        mark: The mark to display in the first column.
        show_context_and_time: Whether to show context usage percent and time.

    Returns:
        A renderable for this metadata block.
    """
    grid = create_grid()

    # Get currency symbol
    currency = metadata.usage.currency if metadata.usage else "USD"
    currency_symbol = "¥" if currency == "CNY" else "$"

    # Second column: provider/model description / tokens / cost / …
    content = Text()
    if metadata.provider is not None:
        content.append_text(Text(metadata.provider.lower().replace(" ", "-"), style=ThemeKey.METADATA))
        content.append_text(Text("/", style=ThemeKey.METADATA))
    content.append_text(Text(metadata.model_name, style=ThemeKey.METADATA))
    if metadata.description:
        content.append_text(Text(" ", style=ThemeKey.METADATA)).append_text(
            Text(metadata.description, style=ThemeKey.METADATA_ITALIC)
        )

    # All info parts (tokens, cost, context, etc.)
    parts: list[Text] = []

    if metadata.usage is not None:
        # Tokens: ↑37k ◎5k ↓907 ∿45k ⌗ 100
        token_text = Text()
        token_text.append("↑", style=ThemeKey.METADATA)
        token_text.append(format_number(metadata.usage.input_tokens), style=ThemeKey.METADATA)
        if metadata.usage.cached_tokens > 0:
            token_text.append(" ◎", style=ThemeKey.METADATA)
            token_text.append(format_number(metadata.usage.cached_tokens), style=ThemeKey.METADATA)
        token_text.append(" ↓", style=ThemeKey.METADATA)
        token_text.append(format_number(metadata.usage.output_tokens), style=ThemeKey.METADATA)
        if metadata.usage.reasoning_tokens > 0:
            token_text.append(" ∿", style=ThemeKey.METADATA)
            token_text.append(format_number(metadata.usage.reasoning_tokens), style=ThemeKey.METADATA)
        if metadata.usage.image_tokens > 0:
            token_text.append(" ⊡", style=ThemeKey.METADATA)
            token_text.append(format_number(metadata.usage.image_tokens), style=ThemeKey.METADATA)
        parts.append(token_text)

    # Cost
    if metadata.usage is not None and metadata.usage.total_cost is not None:
        parts.append(
            Text.assemble(
                (currency_symbol, ThemeKey.METADATA),
                (f"{metadata.usage.total_cost:.4f}", ThemeKey.METADATA),
            )
        )
    if metadata.usage is not None:
        # Context usage: 31k/168k(18.4%)
        if show_context_and_time and metadata.usage.context_usage_percent is not None:
            context_size = format_number(metadata.usage.context_size or 0)
            effective_limit = (metadata.usage.context_limit or 0) - (metadata.usage.max_tokens or DEFAULT_MAX_TOKENS)
            effective_limit_str = format_number(effective_limit) if effective_limit > 0 else "?"
            parts.append(
                Text.assemble(
                    (context_size, ThemeKey.METADATA),
                    ("/", ThemeKey.METADATA),
                    (effective_limit_str, ThemeKey.METADATA),
                    (f"({metadata.usage.context_usage_percent:.1f}%)", ThemeKey.METADATA),
                )
            )

        # TPS: 45.2tps
        if metadata.usage.throughput_tps is not None:
            parts.append(
                Text.assemble(
                    (f"{metadata.usage.throughput_tps:.1f}", ThemeKey.METADATA),
                    ("tps", ThemeKey.METADATA),
                )
            )

        # First token latency: 100ms-ftl / 2.1s-ftl
        if metadata.usage.first_token_latency_ms is not None:
            ftl_ms = metadata.usage.first_token_latency_ms
            ftl_str = f"{ftl_ms / 1000:.1f}s" if ftl_ms >= 1000 else f"{ftl_ms:.0f}ms"
            parts.append(
                Text.assemble(
                    (ftl_str, ThemeKey.METADATA),
                    ("-ftl", ThemeKey.METADATA),
                )
            )

    # Duration: 12.5s
    if show_context_and_time and metadata.task_duration_s is not None:
        parts.append(
            Text.assemble(
                (f"{metadata.task_duration_s:.1f}", ThemeKey.METADATA),
                ("s", ThemeKey.METADATA),
            )
        )

    # Turn count: 1step / 3steps
    if show_context_and_time and metadata.turn_count > 0:
        suffix = "step" if metadata.turn_count == 1 else "steps"
        parts.append(
            Text.assemble(
                (str(metadata.turn_count), ThemeKey.METADATA),
                (suffix, ThemeKey.METADATA),
            )
        )

    if parts:
        content.append_text(Text(" ", style=ThemeKey.METADATA))
        content.append_text(Text(" ", style=ThemeKey.METADATA).join(parts))

    grid.add_row(mark, content)
    return grid


def render_task_metadata(e: events.TaskMetadataEvent) -> RenderableType:
    """Render task metadata including main agent and sub-agents."""
    renderables: list[RenderableType] = []

    has_sub_agents = len(e.metadata.sub_agent_task_metadata) > 0
    # Use an extra space for the main agent mark to align with two-character marks (├─, └─)
    main_mark_text = "●"
    main_mark = Text(main_mark_text, style=ThemeKey.METADATA)

    renderables.append(_render_task_metadata_block(e.metadata.main_agent, mark=main_mark, show_context_and_time=True))

    # Render each sub-agent metadata block
    for meta in e.metadata.sub_agent_task_metadata:
        sub_mark = Text("  └", style=ThemeKey.METADATA)
        renderables.append(_render_task_metadata_block(meta, mark=sub_mark, show_context_and_time=True))

    # Add total cost line when there are sub-agents
    if has_sub_agents:
        total_cost = 0.0
        currency = "USD"
        # Sum up costs from main agent and all sub-agents
        if e.metadata.main_agent.usage and e.metadata.main_agent.usage.total_cost:
            total_cost += e.metadata.main_agent.usage.total_cost
            currency = e.metadata.main_agent.usage.currency
        for meta in e.metadata.sub_agent_task_metadata:
            if meta.usage and meta.usage.total_cost:
                total_cost += meta.usage.total_cost

        currency_symbol = "¥" if currency == "CNY" else "$"
        total_line = Text.assemble(
            ("  └", ThemeKey.METADATA),
            (" Σ ", ThemeKey.METADATA),
            ("total ", ThemeKey.METADATA),
            (currency_symbol, ThemeKey.METADATA),
            (f"{total_cost:.4f}", ThemeKey.METADATA),
        )

        renderables.append(total_line)

    return Group(*renderables)
