from rich import box
from rich.box import Box
from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.rule import Rule
from rich.text import Text

from codex_mini.protocol import events
from codex_mini.ui.theme import ThemeKey
from codex_mini.ui.utils import format_number


def render_response_metadata(e: events.ResponseMetadataEvent) -> RenderableType:
    metadata = e.metadata
    rule_text = Text()
    rule_text.append_text(Text("↑ ", style=ThemeKey.METADATA_BOLD))
    rule_text.append_text(Text(metadata.model_name, style=ThemeKey.METADATA_BOLD))
    if metadata.provider is not None:
        rule_text.append_text(Text(" "))
        rule_text.append_text(Text(metadata.provider.lower(), style=ThemeKey.METADATA))
    if metadata.usage is not None:
        cached_token_str = (
            Text.assemble((", ", ThemeKey.METADATA_DIM), format_number(metadata.usage.cached_tokens), " cached")
            if metadata.usage.cached_tokens > 0
            else Text("")
        )
        reasoning_token_str = (
            Text.assemble((", ", ThemeKey.METADATA_DIM), format_number(metadata.usage.reasoning_tokens), " reasoning")
            if metadata.usage.reasoning_tokens > 0
            else Text("")
        )
        context_usage_str = (
            Text.assemble((", ", ThemeKey.METADATA_DIM), f"{metadata.usage.context_usage_percent:.1f}%", " context")
            if metadata.usage.context_usage_percent is not None
            else Text("")
        )

        throughput_str = (
            Text.assemble((", ", ThemeKey.METADATA_DIM), f"{metadata.usage.throughput_tps:.1f}", " tps")
            if metadata.usage.throughput_tps is not None
            else Text("")
        )
        latency_str = (
            Text.assemble((", ", ThemeKey.METADATA_DIM), f"{metadata.usage.first_token_latency_ms:.0f} ms", " latency")
            if metadata.usage.first_token_latency_ms is not None
            else Text("")
        )

        rule_text.append_text(
            Text.assemble(
                (" · ", ThemeKey.METADATA_DIM),
                (format_number(metadata.usage.input_tokens), ThemeKey.METADATA),
                (" input"),
                cached_token_str,
                (", ", ThemeKey.METADATA_DIM),
                (format_number(metadata.usage.output_tokens), ThemeKey.METADATA),
                (" output"),
                reasoning_token_str,
                context_usage_str,
                throughput_str,
                latency_str,
                style=ThemeKey.METADATA,
            )
        )
    return Rule(rule_text, style=ThemeKey.LINES, align="left", characters="-")


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


def render_resume_loading() -> RenderableType:
    return Text.assemble(Text(" LOADING ", style=ThemeKey.RESUME_FLAG))


def render_resume_loaded(updated_at: float) -> RenderableType:
    from time import localtime, strftime

    return Text.assemble(
        Text(" LOADED ", style=ThemeKey.RESUME_FLAG),
        Text(f" ◷ {strftime('%Y-%m-%d %H:%M:%S', localtime(updated_at))}", style=ThemeKey.RESUME_INFO),
    )
