from importlib.metadata import version

from rich import box
from rich.box import Box
from rich.console import Group, RenderableType
from rich.padding import Padding
from rich.panel import Panel
from rich.text import Text

from klaude_code.protocol import events
from klaude_code.ui.base.theme import ThemeKey
from klaude_code.ui.base.utils import format_number


def _get_version() -> str:
    """Get the current version of klaude-code."""
    try:
        return version("klaude-code")
    except Exception:
        return "unknown"


def render_response_metadata(e: events.ResponseMetadataEvent) -> RenderableType:
    metadata = e.metadata

    # Line 1: Model and Provider
    model_text = Text()
    model_text.append_text(Text("▪ ", style=ThemeKey.METADATA)).append_text(
        Text(metadata.model_name, style=ThemeKey.METADATA_BOLD)
    )
    if metadata.provider is not None:
        model_text.append_text(Text("@", style=ThemeKey.METADATA)).append_text(
            Text(metadata.provider.lower().replace(" ", "-"), style=ThemeKey.METADATA)
        )

    renderables: list[RenderableType] = [model_text]

    # Line 2: Token consumption, Context, TPS, Cost
    parts: list[Text] = []

    if metadata.usage is not None:
        # Input
        parts.append(
            Text.assemble(
                ("input:", ThemeKey.METADATA_DIM),
                (format_number(metadata.usage.input_tokens), ThemeKey.METADATA_DIM),
            )
        )

        # Cached
        if metadata.usage.cached_tokens > 0:
            parts.append(
                Text.assemble(
                    ("cached", ThemeKey.METADATA_DIM),
                    (":", ThemeKey.METADATA_DIM),
                    (format_number(metadata.usage.cached_tokens), ThemeKey.METADATA_DIM),
                )
            )

        # Output
        parts.append(
            Text.assemble(
                ("output:", ThemeKey.METADATA_DIM),
                (format_number(metadata.usage.output_tokens), ThemeKey.METADATA_DIM),
            )
        )

        # Reasoning
        if metadata.usage.reasoning_tokens > 0:
            parts.append(
                Text.assemble(
                    ("thinking", ThemeKey.METADATA_DIM),
                    (":", ThemeKey.METADATA_DIM),
                    (format_number(metadata.usage.reasoning_tokens), ThemeKey.METADATA_DIM),
                )
            )

        # Context
        if metadata.usage.context_usage_percent is not None:
            parts.append(
                Text.assemble(
                    ("context", ThemeKey.METADATA_DIM),
                    (":", ThemeKey.METADATA_DIM),
                    (f"{metadata.usage.context_usage_percent:.1f}%", ThemeKey.METADATA_DIM),
                )
            )

        # TPS
        if metadata.usage.throughput_tps is not None:
            parts.append(
                Text.assemble(
                    ("tps", ThemeKey.METADATA_DIM),
                    (":", ThemeKey.METADATA_DIM),
                    (f"{metadata.usage.throughput_tps:.1f}", ThemeKey.METADATA_DIM),
                )
            )

    # Cost
    if metadata.task_duration_s is not None:
        parts.append(
            Text.assemble(
                ("cost", ThemeKey.METADATA_DIM),
                (":", ThemeKey.METADATA_DIM),
                (f"{metadata.task_duration_s:.1f}s", ThemeKey.METADATA_DIM),
            )
        )

    if parts:
        line2 = Text("/", style=ThemeKey.METADATA_DIM).join(parts)
        renderables.append(Padding(line2, (0, 0, 0, 2)))

    return Group(*renderables)


def render_welcome(e: events.WelcomeEvent, *, box_style: Box | None = None) -> RenderableType:
    """Render the welcome panel with model info and settings."""
    if box_style is None:
        box_style = box.ROUNDED

    # First line: Klaude Code version
    panel_content = Text.assemble(
        ("Klaude Code", ThemeKey.WELCOME_HIGHLIGHT),
        (f" v{_get_version()}\n", ThemeKey.WELCOME_INFO),
        (str(e.llm_config.model), ThemeKey.WELCOME_HIGHLIGHT),
        (" @ ", ThemeKey.WELCOME_INFO),
        (e.llm_config.provider_name, ThemeKey.WELCOME_INFO),
    )

    if e.llm_config.thinking is not None:
        if e.llm_config.thinking.reasoning_effort:
            panel_content.append_text(
                Text.assemble(
                    ("\n• reasoning-effort: ", ThemeKey.WELCOME_INFO),
                    (e.llm_config.thinking.reasoning_effort, ThemeKey.WELCOME_HIGHLIGHT),
                )
            )
        if e.llm_config.thinking.reasoning_summary:
            panel_content.append_text(
                Text.assemble(
                    ("\n• reasoning-summary: ", ThemeKey.WELCOME_INFO),
                    (e.llm_config.thinking.reasoning_summary, ThemeKey.WELCOME_HIGHLIGHT),
                )
            )
        if e.llm_config.thinking.budget_tokens:
            panel_content.append_text(
                Text.assemble(
                    ("\n• thinking-budget: ", ThemeKey.WELCOME_INFO),
                    (str(e.llm_config.thinking.budget_tokens), ThemeKey.WELCOME_HIGHLIGHT),
                )
            )
    if e.llm_config.verbosity:
        panel_content.append_text(
            Text.assemble(
                ("\n• verbosity: ", ThemeKey.WELCOME_INFO), (str(e.llm_config.verbosity), ThemeKey.WELCOME_HIGHLIGHT)
            )
        )

    if pr := e.llm_config.provider_routing:
        if pr.sort:
            panel_content.append_text(
                Text.assemble(
                    ("\n• provider-sort: ", ThemeKey.WELCOME_INFO), (str(pr.sort), ThemeKey.WELCOME_HIGHLIGHT)
                )
            )
        if pr.only:
            panel_content.append_text(
                Text.assemble(
                    ("\n• provider-only: ", ThemeKey.WELCOME_INFO), (">".join(pr.only), ThemeKey.WELCOME_HIGHLIGHT)
                )
            )
        if pr.order:
            panel_content.append_text(
                Text.assemble(
                    ("\n• provider-order: ", ThemeKey.WELCOME_INFO), (">".join(pr.order), ThemeKey.WELCOME_HIGHLIGHT)
                )
            )

    return Group(
        Panel.fit(panel_content, border_style=ThemeKey.LINES, box=box_style),
        "",  # empty line
    )


def render_resume_loaded(updated_at: float) -> RenderableType:
    from time import localtime, strftime

    return Text.assemble(
        Text(" LOADED ", style=ThemeKey.RESUME_FLAG),
        Text(f" ◷ {strftime('%Y-%m-%d %H:%M:%S', localtime(updated_at))}", style=ThemeKey.RESUME_INFO),
    )
