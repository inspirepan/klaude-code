from rich import box
from rich.box import Box
from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.text import Text

from codex_mini.protocol import events
from codex_mini.ui.theme import ThemeKey
from codex_mini.ui.utils import format_number


def render_response_metadata(e: events.ResponseMetadataEvent) -> RenderableType:
    metadata = e.metadata
    metadata_text = Text()
    metadata_text.append_text(Text("↑ ", style=ThemeKey.METADATA_BOLD)).append_text(
        Text(metadata.model_name, style=ThemeKey.METADATA_BOLD)
    )
    if metadata.provider is not None:
        metadata_text.append_text(Text(" ")).append_text(Text(metadata.provider.lower(), style=ThemeKey.METADATA))

    detail_parts: list[Text] = []

    if metadata.usage is not None:
        detail_parts.append(
            Text.assemble(
                (format_number(metadata.usage.input_tokens), ThemeKey.METADATA_BOLD), (" input", ThemeKey.METADATA)
            )
        )

        if metadata.usage.cached_tokens > 0:
            detail_parts.append(
                Text.assemble(
                    (format_number(metadata.usage.cached_tokens), ThemeKey.METADATA_BOLD),
                    (" cached", ThemeKey.METADATA),
                )
            )

        detail_parts.append(
            Text.assemble(
                (format_number(metadata.usage.output_tokens), ThemeKey.METADATA_BOLD), (" output", ThemeKey.METADATA)
            )
        )

        if metadata.usage.reasoning_tokens > 0:
            detail_parts.append(
                Text.assemble(
                    (format_number(metadata.usage.reasoning_tokens), ThemeKey.METADATA_BOLD),
                    (" reasoning", ThemeKey.METADATA),
                )
            )

        if metadata.usage.context_usage_percent is not None:
            detail_parts.append(
                Text.assemble(
                    (f"{metadata.usage.context_usage_percent:.1f}", ThemeKey.METADATA_BOLD),
                    ("% context", ThemeKey.METADATA),
                )
            )

        if metadata.usage.throughput_tps is not None:
            detail_parts.append(
                Text.assemble(
                    (f"{metadata.usage.throughput_tps:.1f}", ThemeKey.METADATA_BOLD),
                    (" tps", ThemeKey.METADATA),
                )
            )

        # if metadata.usage.first_token_latency_ms is not None:
        #     usage_parts.append(
        #         Text.assemble(
        #             ("avg first token latency: ", ThemeKey.METADATA),
        #             (f"{metadata.usage.first_token_latency_ms:.0f} ms", ThemeKey.METADATA_BOLD),
        #         )
        #     )

    if metadata.task_duration_s is not None:
        detail_parts.append(
            Text.assemble(
                (f"{metadata.task_duration_s:.1f}", ThemeKey.METADATA_BOLD),
                ("s", ThemeKey.METADATA),
            )
        )

    if metadata.turn_count is not None:
        detail_parts.append(
            Text.assemble(
                (str(metadata.turn_count), ThemeKey.METADATA_BOLD),
                (" turns", ThemeKey.METADATA),
            )
        )

    if detail_parts:
        metadata_text.append_text(Text(" · ", style=ThemeKey.METADATA)).append_text(
            Text(", ", style=ThemeKey.METADATA).join(detail_parts)
        )
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

    if e.llm_config.reasoning is not None and e.llm_config.reasoning.effort:
        model_info.append_text(
            Text.assemble(
                ("\n• reasoning-effort: ", ThemeKey.WELCOME_INFO),
                (e.llm_config.reasoning.effort, ThemeKey.WELCOME_HIGHLIGHT),
            )
        )
    if e.llm_config.reasoning is not None and e.llm_config.reasoning.summary:
        model_info.append_text(
            Text.assemble(
                ("\n• reasoning-summary: ", ThemeKey.WELCOME_INFO),
                (e.llm_config.reasoning.summary, ThemeKey.WELCOME_HIGHLIGHT),
            )
        )
    if e.llm_config.thinking is not None and e.llm_config.thinking.budget_tokens:
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

    if pl := e.llm_config.plugins:
        model_info.append_text(Text.assemble(("\n•", ThemeKey.WELCOME_INFO)))
        for p in pl:
            model_info.append_text(Text.assemble(" ", (p.id, ThemeKey.WELCOME_HIGHLIGHT)))

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
