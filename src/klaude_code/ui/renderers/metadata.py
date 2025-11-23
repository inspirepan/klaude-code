from rich import box
from rich.box import Box
from rich.console import Group, RenderableType
from rich.padding import Padding
from rich.panel import Panel
from rich.text import Text

from klaude_code.protocol import events
from klaude_code.ui.base.theme import ThemeKey
from klaude_code.ui.base.utils import format_number


def render_response_metadata(e: events.ResponseMetadataEvent) -> RenderableType:
    metadata = e.metadata

    # Line 1: Model and Provider
    model_text = Text()
    model_text.append_text(Text("↑ ", style=ThemeKey.METADATA)).append_text(
        Text(metadata.model_name, style=ThemeKey.METADATA_BOLD)
    )
    if metadata.provider is not None:
        model_text.append_text(Text("@", style=ThemeKey.METADATA_DIM)).append_text(
            Text(metadata.provider.lower().replace(" ", "-"), style=ThemeKey.METADATA_DIM)
        )

    renderables: list[RenderableType] = [model_text]

    # Line 2: Token consumption
    if metadata.usage is not None:
        token_parts: list[Text] = []
        # Input
        token_parts.append(
            Text.assemble(
                ("input:", ThemeKey.METADATA_DIM),
                (format_number(metadata.usage.input_tokens), ThemeKey.METADATA_DIM),
            )
        )

        # Cached
        if metadata.usage.cached_tokens > 0:
            token_parts.append(
                Text.assemble(
                    ("cached", ThemeKey.METADATA_DIM),
                    (":", ThemeKey.METADATA_DIM),
                    (format_number(metadata.usage.cached_tokens), ThemeKey.METADATA_DIM),
                )
            )

        # Output
        token_parts.append(
            Text.assemble(
                ("output:", ThemeKey.METADATA_DIM),
                (format_number(metadata.usage.output_tokens), ThemeKey.METADATA_DIM),
            )
        )

        # Reasoning
        if metadata.usage.reasoning_tokens > 0:
            token_parts.append(
                Text.assemble(
                    ("reasoning", ThemeKey.METADATA_DIM),
                    (":", ThemeKey.METADATA_DIM),
                    (format_number(metadata.usage.reasoning_tokens), ThemeKey.METADATA_DIM),
                )
            )

        if token_parts:
            line2 = Text("  ", style=ThemeKey.METADATA_DIM).join(token_parts)
            renderables.append(Padding(line2, (0, 0, 0, 2)))

    # Line 3: Context, TPS, Cost
    stats_parts: list[Text] = []

    if metadata.usage is not None:
        if metadata.usage.context_usage_percent is not None:
            stats_parts.append(
                Text.assemble(
                    ("context", ThemeKey.METADATA_DIM),
                    (":", ThemeKey.METADATA_DIM),
                    (f"{metadata.usage.context_usage_percent:.1f}%", ThemeKey.METADATA_DIM),
                )
            )

        if metadata.usage.throughput_tps is not None:
            stats_parts.append(
                Text.assemble(
                    ("tps", ThemeKey.METADATA_DIM),
                    (":", ThemeKey.METADATA_DIM),
                    (f"{metadata.usage.throughput_tps:.1f}", ThemeKey.METADATA_DIM),
                )
            )

    if metadata.task_duration_s is not None:
        stats_parts.append(
            Text.assemble(
                ("cost", ThemeKey.METADATA_DIM),
                (":", ThemeKey.METADATA_DIM),
                (f"{metadata.task_duration_s:.1f}s", ThemeKey.METADATA_DIM),
            )
        )

    if stats_parts:
        line3 = Text("  ", style=ThemeKey.METADATA_DIM).join(stats_parts)
        renderables.append(Padding(line3, (0, 0, 0, 2)))

    return Group(*renderables)


def render_welcome(e: events.WelcomeEvent, *, box_style: Box | None = None) -> RenderableType:
    """Render the welcome panel with model info and settings."""
    if box_style is None:
        box_style = box.ROUNDED

    model_info = Text.assemble(
        (str(e.llm_config.model), ThemeKey.WELCOME_HIGHLIGHT),
        (" @ ", ThemeKey.WELCOME_INFO),
        (e.llm_config.provider_name, ThemeKey.WELCOME_INFO),
    )

    if e.llm_config.thinking is not None:
        if e.llm_config.thinking.reasoning_effort:
            model_info.append_text(
                Text.assemble(
                    ("\n• reasoning-effort: ", ThemeKey.WELCOME_INFO),
                    (e.llm_config.thinking.reasoning_effort, ThemeKey.WELCOME_HIGHLIGHT),
                )
            )
        if e.llm_config.thinking.reasoning_summary:
            model_info.append_text(
                Text.assemble(
                    ("\n• reasoning-summary: ", ThemeKey.WELCOME_INFO),
                    (e.llm_config.thinking.reasoning_summary, ThemeKey.WELCOME_HIGHLIGHT),
                )
            )
        if e.llm_config.thinking.budget_tokens:
            model_info.append_text(
                Text.assemble(
                    ("\n• thinking-budget: ", ThemeKey.WELCOME_INFO),
                    (str(e.llm_config.thinking.budget_tokens), ThemeKey.WELCOME_HIGHLIGHT),
                )
            )
    if e.llm_config.verbosity:
        model_info.append_text(
            Text.assemble(
                ("\n• verbosity: ", ThemeKey.WELCOME_INFO), (str(e.llm_config.verbosity), ThemeKey.WELCOME_HIGHLIGHT)
            )
        )

    if pr := e.llm_config.provider_routing:
        if pr.sort:
            model_info.append_text(
                Text.assemble(
                    ("\n• provider-sort: ", ThemeKey.WELCOME_INFO), (str(pr.sort), ThemeKey.WELCOME_HIGHLIGHT)
                )
            )
        if pr.only:
            model_info.append_text(
                Text.assemble(
                    ("\n• provider-only: ", ThemeKey.WELCOME_INFO), (">".join(pr.only), ThemeKey.WELCOME_HIGHLIGHT)
                )
            )
        if pr.order:
            model_info.append_text(
                Text.assemble(
                    ("\n• provider-order: ", ThemeKey.WELCOME_INFO), (">".join(pr.order), ThemeKey.WELCOME_HIGHLIGHT)
                )
            )

    return Group(
        Panel.fit(model_info, border_style=ThemeKey.LINES, box=box_style),
        "",  # empty line
    )


def render_resume_loaded(updated_at: float) -> RenderableType:
    from time import localtime, strftime

    return Text.assemble(
        Text(" LOADED ", style=ThemeKey.RESUME_FLAG),
        Text(f" ◷ {strftime('%Y-%m-%d %H:%M:%S', localtime(updated_at))}", style=ThemeKey.RESUME_INFO),
    )
