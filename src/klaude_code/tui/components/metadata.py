from typing import ClassVar

from rich.console import Group, RenderableType
from rich.text import Text
from rich.tree import Tree

from klaude_code.const import DEFAULT_MAX_TOKENS, LOW_CACHE_HIT_RATE_THRESHOLD
from klaude_code.protocol import events, model
from klaude_code.tui.components.common import create_grid, format_elapsed_compact
from klaude_code.tui.components.rich.theme import ThemeKey
from klaude_code.ui.common import format_number

WORKED_LINE_DURATION_THRESHOLD_S = 60
WORKED_LINE_TURN_COUNT_THRESHOLD = 4


class _RoundedTree(Tree):
    TREE_GUIDES: ClassVar[list[tuple[str, str, str, str]]] = [
        ("      ", "  │   ", "  ├── ", "  ╰── "),
        ("      ", "  │   ", "  ├── ", "  ╰── "),
        ("      ", "  │   ", "  ├── ", "  ╰── "),
    ]


def _build_metadata_content(
    metadata: model.TaskMetadata,
    *,
    show_context_and_time: bool = True,
    show_turn_count: bool = True,
    show_duration: bool = True,
) -> RenderableType:
    """Build the content renderable for a single metadata block."""
    currency = metadata.usage.currency if metadata.usage else "USD"
    currency_symbol = "¥" if currency == "CNY" else "$"

    sub_agent_description_in_details = bool(metadata.sub_agent_name and metadata.description)

    identity = Text()
    if metadata.sub_agent_name:
        identity.append_text(Text(f" {metadata.sub_agent_name} ", style=ThemeKey.METADATA_SUB_AGENT_NAME))
        identity.append_text(Text(" ", style=ThemeKey.METADATA))
    if metadata.description and not sub_agent_description_in_details:
        identity.append_text(Text(metadata.description, style=ThemeKey.METADATA_ITALIC))
        identity.append_text(Text(" ", style=ThemeKey.METADATA))
    identity.append_text(Text(metadata.model_name, style=ThemeKey.METADATA))

    parts: list[Text] = []
    if sub_agent_description_in_details:
        parts.append(Text(metadata.description, style=ThemeKey.METADATA_ITALIC))

    if metadata.provider:
        sub_provider = metadata.provider.rsplit("/", 1)[-1] if "/" in metadata.provider else metadata.provider
        parts.append(Text(f"via {sub_provider}", style=ThemeKey.METADATA_DIM))

    if metadata.usage is not None and metadata.usage.total_cost is not None:
        parts.append(
            Text.assemble(
                (currency_symbol, ThemeKey.METADATA),
                (f"{metadata.usage.total_cost:.4f}", ThemeKey.METADATA),
            )
        )

    if metadata.usage is not None:
        token_text = Text()
        input_tokens = max(metadata.usage.input_tokens - metadata.usage.cached_tokens, 0)
        output_tokens = max(metadata.usage.output_tokens - metadata.usage.reasoning_tokens, 0)

        token_text.append("input ", style=ThemeKey.METADATA)
        token_text.append(format_number(input_tokens), style=ThemeKey.METADATA)
        if metadata.usage.cached_tokens > 0:
            token_text.append(", cache ", style=ThemeKey.METADATA)
            token_text.append(format_number(metadata.usage.cached_tokens), style=ThemeKey.METADATA)
            if metadata.usage.cache_hit_rate is not None:
                if metadata.usage.cache_hit_rate >= 0.995:
                    rate_style = ThemeKey.METADATA_GREEN
                elif metadata.usage.cache_hit_rate >= LOW_CACHE_HIT_RATE_THRESHOLD:
                    rate_style = ThemeKey.METADATA
                else:
                    rate_style = ThemeKey.WARN
                token_text.append(f" (hit {metadata.usage.cache_hit_rate:.0%})", style=rate_style)
        token_text.append(", output ", style=ThemeKey.METADATA)
        token_text.append(format_number(output_tokens), style=ThemeKey.METADATA)
        if metadata.usage.reasoning_tokens > 0:
            token_text.append(", thought ", style=ThemeKey.METADATA)
            token_text.append(format_number(metadata.usage.reasoning_tokens), style=ThemeKey.METADATA)
        if metadata.usage.image_tokens > 0:
            token_text.append(", img ", style=ThemeKey.METADATA)
            token_text.append(format_number(metadata.usage.image_tokens), style=ThemeKey.METADATA)
        parts.append(token_text)

        # Context pill (blue-grey bg): "25.1k/168k (14.9%)"
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

        if metadata.usage.throughput_tps is not None:
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

    if show_duration and show_context_and_time and metadata.task_duration_s is not None:
        parts.append(Text(format_elapsed_compact(metadata.task_duration_s), style=ThemeKey.METADATA))

    if not parts:
        return identity

    details = Text(", ", style=ThemeKey.METADATA_DIM).join(parts)
    content_grid = create_grid()
    content_grid.add_row(identity, details)
    return content_grid


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
    main_content = _build_metadata_content(
        main,
        show_context_and_time=True,
        show_turn_count=not should_show_worked_line,
        show_duration=not should_show_worked_line,
    )

    if has_sub_agents:
        root_content = create_grid()
        root_content.add_row(Text(" Main ", style=ThemeKey.METADATA_MAIN_AGENT_NAME), main_content)
        root_grid = create_grid()
        root_grid.add_row(Text("•", style=ThemeKey.METADATA), root_content)
        tree = _RoundedTree(root_grid, guide_style=ThemeKey.METADATA_DIM)

        for meta in e.metadata.sub_agent_task_metadata:
            tree.add(_build_metadata_content(meta, show_context_and_time=True))

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
                ("total ", ThemeKey.METADATA),
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


def render_cache_hit_warn(e: events.CacheHitWarnEvent) -> RenderableType:
    """Render a warning when per-turn cache hit rate drops below 90%."""
    grid = create_grid()
    msg = Text.assemble(
        ("Low cache hit rate: ", ThemeKey.WARN),
        (f"{e.cache_hit_rate:.0%}", ThemeKey.WARN_BOLD),
        (f" (cached {format_number(e.cached_tokens)}", ThemeKey.WARN),
        (f" / prev input {format_number(e.prev_turn_input_tokens)})", ThemeKey.WARN),
    )
    grid.add_row(Text("!", style=ThemeKey.WARN_BOLD), msg)
    return grid
