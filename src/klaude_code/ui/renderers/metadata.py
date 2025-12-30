from importlib.metadata import PackageNotFoundError, version

from rich import box
from rich.console import Group, RenderableType
from rich.padding import Padding
from rich.panel import Panel
from rich.text import Text

from klaude_code import const
from klaude_code.protocol import events, model
from klaude_code.trace import is_debug_enabled
from klaude_code.ui.renderers.common import create_grid
from klaude_code.ui.rich.theme import ThemeKey
from klaude_code.ui.utils.common import format_number


def _get_version() -> str:
    """Get the current version of klaude-code."""
    try:
        return version("klaude-code")
    except PackageNotFoundError:
        return "unknown"


def _render_task_metadata_block(
    metadata: model.TaskMetadata,
    *,
    is_sub_agent: bool = False,
    show_context_and_time: bool = True,
) -> RenderableType:
    """Render a single TaskMetadata block.

    Args:
        metadata: The TaskMetadata to render.
        is_sub_agent: Whether this is a sub-agent block.
        show_context_and_time: Whether to show context usage percent and time.

    Returns:
        A renderable for this metadata block.
    """
    grid = create_grid()

    # Get currency symbol
    currency = metadata.usage.currency if metadata.usage else "USD"
    currency_symbol = "¥" if currency == "CNY" else "$"

    # First column: mark only
    mark = Text("└", style=ThemeKey.METADATA_DIM) if is_sub_agent else Text("⇅", style=ThemeKey.METADATA)

    # Second column: model@provider / tokens / cost / ...
    content = Text()
    content.append_text(Text(metadata.model_name, style=ThemeKey.METADATA_BOLD))
    if metadata.provider is not None:
        content.append_text(Text("@", style=ThemeKey.METADATA)).append_text(
            Text(metadata.provider.lower().replace(" ", "-"), style=ThemeKey.METADATA)
        )

    # All info parts (tokens, cost, context, etc.)
    parts: list[Text] = []

    if metadata.usage is not None:
        # Tokens: ↑ 37k cache 5k ↓ 907 think 45k
        token_parts: list[Text] = [
            Text.assemble(("↑", ThemeKey.METADATA_DIM), (format_number(metadata.usage.input_tokens), ThemeKey.METADATA))
        ]
        if metadata.usage.cached_tokens > 0:
            token_parts.append(
                Text.assemble(
                    Text("cache ", style=ThemeKey.METADATA_DIM),
                    Text(format_number(metadata.usage.cached_tokens), style=ThemeKey.METADATA),
                )
            )
        token_parts.append(
            Text.assemble(
                ("↓", ThemeKey.METADATA_DIM), (format_number(metadata.usage.output_tokens), ThemeKey.METADATA)
            )
        )
        if metadata.usage.reasoning_tokens > 0:
            token_parts.append(
                Text.assemble(
                    ("think ", ThemeKey.METADATA_DIM),
                    (format_number(metadata.usage.reasoning_tokens), ThemeKey.METADATA),
                )
            )
        parts.append(Text(" · ").join(token_parts))

    # Cost
    if metadata.usage is not None and metadata.usage.total_cost is not None:
        parts.append(
            Text.assemble(
                (currency_symbol, ThemeKey.METADATA_DIM),
                (f"{metadata.usage.total_cost:.4f}", ThemeKey.METADATA),
            )
        )
    if metadata.usage is not None:
        # Context (only for main agent)
        if show_context_and_time and metadata.usage.context_usage_percent is not None:
            context_size = format_number(metadata.usage.context_size or 0)
            # Calculate effective limit (same as Usage.context_usage_percent)
            effective_limit = (metadata.usage.context_limit or 0) - (
                metadata.usage.max_tokens or const.DEFAULT_MAX_TOKENS
            )
            effective_limit_str = format_number(effective_limit) if effective_limit > 0 else "?"
            parts.append(
                Text.assemble(
                    ("context ", ThemeKey.METADATA_DIM),
                    (context_size, ThemeKey.METADATA),
                    ("/", ThemeKey.METADATA_DIM),
                    (effective_limit_str, ThemeKey.METADATA),
                    (f" ({metadata.usage.context_usage_percent:.1f}%)", ThemeKey.METADATA_DIM),
                )
            )

        # TPS
        if metadata.usage.throughput_tps is not None:
            parts.append(
                Text.assemble(
                    (f"{metadata.usage.throughput_tps:.1f} ", ThemeKey.METADATA),
                    ("avg-tps", ThemeKey.METADATA_DIM),
                )
            )

        # First token latency
        if metadata.usage.first_token_latency_ms is not None:
            parts.append(
                Text.assemble(
                    (f"{metadata.usage.first_token_latency_ms:.0f}", ThemeKey.METADATA),
                    ("ms avg-ftl", ThemeKey.METADATA_DIM),
                )
            )

    # Duration
    if show_context_and_time and metadata.task_duration_s is not None:
        parts.append(
            Text.assemble(
                (f"{metadata.task_duration_s:.1f}", ThemeKey.METADATA),
                ("s", ThemeKey.METADATA_DIM),
            )
        )

    # Turn count
    if show_context_and_time and metadata.turn_count > 0:
        parts.append(
            Text.assemble(
                (str(metadata.turn_count), ThemeKey.METADATA),
                (" turns", ThemeKey.METADATA_DIM),
            )
        )

    if parts:
        content.append_text(Text(" · ", style=ThemeKey.METADATA_DIM))
        content.append_text(Text(" · ", style=ThemeKey.METADATA_DIM).join(parts))

    grid.add_row(mark, content)
    return grid if not is_sub_agent else Padding(grid, (0, 0, 0, 2))


def render_task_metadata(e: events.TaskMetadataEvent) -> RenderableType:
    """Render task metadata including main agent and sub-agents."""
    renderables: list[RenderableType] = []

    renderables.append(
        _render_task_metadata_block(e.metadata.main_agent, is_sub_agent=False, show_context_and_time=True)
    )

    # Render each sub-agent metadata block
    for meta in e.metadata.sub_agent_task_metadata:
        renderables.append(_render_task_metadata_block(meta, is_sub_agent=True, show_context_and_time=False))

    return Group(*renderables)


def render_welcome(e: events.WelcomeEvent) -> RenderableType:
    """Render the welcome panel with model info and settings."""
    debug_mode = is_debug_enabled()

    # First line: Klaude Code version
    klaude_code_style = ThemeKey.WELCOME_DEBUG_TITLE if debug_mode else ThemeKey.WELCOME_HIGHLIGHT_BOLD
    panel_content = Text.assemble(
        ("Klaude Code", klaude_code_style),
        (f" v{_get_version()}\n", ThemeKey.WELCOME_INFO),
        (str(e.llm_config.model), ThemeKey.WELCOME_HIGHLIGHT),
        (" @ ", ThemeKey.WELCOME_INFO),
        (e.llm_config.provider_name, ThemeKey.WELCOME_INFO),
    )

    # Collect all config items to display
    config_items: list[tuple[str, str]] = []

    if e.llm_config.thinking is not None:
        if e.llm_config.thinking.reasoning_effort:
            config_items.append(("reasoning-effort", e.llm_config.thinking.reasoning_effort))
        if e.llm_config.thinking.reasoning_summary:
            config_items.append(("reasoning-summary", e.llm_config.thinking.reasoning_summary))
        if e.llm_config.thinking.budget_tokens:
            config_items.append(("thinking-budget", str(e.llm_config.thinking.budget_tokens)))

    if e.llm_config.verbosity:
        config_items.append(("verbosity", str(e.llm_config.verbosity)))

    if pr := e.llm_config.provider_routing:
        if pr.sort:
            config_items.append(("provider-sort", str(pr.sort)))
        if pr.only:
            config_items.append(("provider-only", ">".join(pr.only)))
        if pr.order:
            config_items.append(("provider-order", ">".join(pr.order)))

    # Render config items with tree-style prefixes
    for i, (key, value) in enumerate(config_items):
        is_last = i == len(config_items) - 1
        prefix = "└─ " if is_last else "├─ "
        panel_content.append_text(
            Text.assemble(
                ("\n", ThemeKey.WELCOME_INFO),
                (prefix, ThemeKey.LINES),
                (f"{key}: ", ThemeKey.WELCOME_INFO),
                (value, ThemeKey.WELCOME_INFO),
            )
        )

    border_style = ThemeKey.WELCOME_DEBUG_BORDER if debug_mode else ThemeKey.LINES
    return Group(
        Panel.fit(panel_content, border_style=border_style, box=box.ROUNDED),
        "",  # empty line
    )
