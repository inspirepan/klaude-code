from rich import box
from rich.box import Box
from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.text import Text

from klaude_code.protocol import events
from klaude_code.ui.base.theme import ThemeKey
from klaude_code.ui.base.utils import format_number


def render_response_metadata(e: events.ResponseMetadataEvent) -> RenderableType:
    metadata = e.metadata
    metadata_text = Text()
    metadata_text.append_text(Text("↑ ", style=ThemeKey.METADATA)).append_text(
        Text(metadata.model_name, style=ThemeKey.METADATA_BOLD)
    )
    if metadata.provider is not None:
        metadata_text.append_text(Text("@", style=ThemeKey.METADATA_DIM)).append_text(
            Text(metadata.provider.lower().replace(" ", "-"), style=ThemeKey.METADATA_DIM)
        )

    detail_parts: list[Text] = []

    if metadata.usage is not None:
        detail_parts.append(
            Text.assemble(
                ("↑", ThemeKey.METADATA_DIM),
                (format_number(metadata.usage.input_tokens), ThemeKey.METADATA_DIM),
            )
        )

        if metadata.usage.cached_tokens > 0:
            detail_parts.append(
                Text.assemble(
                    ("cached", ThemeKey.METADATA_DIM),
                    (":", ThemeKey.METADATA_DIM),
                    (format_number(metadata.usage.cached_tokens), ThemeKey.METADATA_DIM),
                )
            )

        detail_parts.append(
            Text.assemble(
                ("↓", ThemeKey.METADATA_DIM),
                (format_number(metadata.usage.output_tokens), ThemeKey.METADATA_DIM),
            )
        )

        if metadata.usage.reasoning_tokens > 0:
            detail_parts.append(
                Text.assemble(
                    ("reasoning", ThemeKey.METADATA_DIM),
                    (":", ThemeKey.METADATA_DIM),
                    (format_number(metadata.usage.reasoning_tokens), ThemeKey.METADATA_DIM),
                )
            )

        if metadata.usage.context_usage_percent is not None:
            detail_parts.append(
                Text.assemble(
                    ("context", ThemeKey.METADATA_DIM),
                    (":", ThemeKey.METADATA_DIM),
                    (f"{metadata.usage.context_usage_percent:.1f}%", ThemeKey.METADATA_DIM),
                )
            )

        if metadata.usage.throughput_tps is not None:
            detail_parts.append(
                Text.assemble(
                    ("tps", ThemeKey.METADATA_DIM),
                    (":", ThemeKey.METADATA_DIM),
                    (f"{metadata.usage.throughput_tps:.1f}", ThemeKey.METADATA_DIM),
                )
            )

    if metadata.task_duration_s is not None:
        detail_parts.append(
            Text.assemble(
                ("cost", ThemeKey.METADATA_DIM),
                (":", ThemeKey.METADATA_DIM),
                (f"{metadata.task_duration_s:.1f}s", ThemeKey.METADATA_DIM),
            )
        )

    if detail_parts:
        details = Text()
        for i, part in enumerate(detail_parts):
            if i > 0:
                details.append("/", style=ThemeKey.METADATA_DIM)
            details.append_text(part)
        metadata_text.append_text(Text(" ", style=ThemeKey.METADATA_DIM)).append_text(details)
    return metadata_text


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
        if e.llm_config.thinking.thinking_budget:
            model_info.append_text(
                Text.assemble(
                    ("\n• thinking-budget: ", ThemeKey.WELCOME_INFO),
                    (str(e.llm_config.thinking.thinking_budget), ThemeKey.WELCOME_HIGHLIGHT),
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
