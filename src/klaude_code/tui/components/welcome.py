from importlib.metadata import PackageNotFoundError, version

from rich.console import Group, RenderableType
from rich.text import Text

from klaude_code.log import is_debug_enabled
from klaude_code.protocol import events
from klaude_code.tui.components.rich.quote import Quote
from klaude_code.tui.components.rich.theme import ThemeKey
from klaude_code.ui.common import format_model_params


def _get_version() -> str:
    """Get the current version of klaude-code."""
    try:
        return version("klaude-code")
    except PackageNotFoundError:
        return "unknown"


def render_welcome(e: events.WelcomeEvent) -> RenderableType:
    """Render the welcome panel with model info and settings.

    Args:
        e: The welcome event.
    """
    debug_mode = is_debug_enabled()

    panel_content = Text()

    if e.show_klaude_code_info:
        # First line: Klaude Code version
        klaude_code_style = ThemeKey.WELCOME_DEBUG_TITLE if debug_mode else ThemeKey.WELCOME_HIGHLIGHT_BOLD
        panel_content.append_text(Text("Klaude Code", style=klaude_code_style))
        panel_content.append_text(Text(f" v{_get_version()}", style=ThemeKey.WELCOME_INFO))
        panel_content.append_text(Text("\n"))

    # Model line: model @ provider · params...
    panel_content.append_text(
        Text.assemble(
            (str(e.llm_config.model), ThemeKey.WELCOME_HIGHLIGHT),
            (" @ ", ThemeKey.WELCOME_INFO),
            (e.llm_config.provider_name, ThemeKey.WELCOME_INFO),
        )
    )

    # Use format_model_params for consistent formatting
    param_strings = format_model_params(e.llm_config)

    # Check if we have sub-agent models to show
    has_sub_agents = e.show_sub_agent_models and e.sub_agent_models

    # Render config items with tree-style prefixes
    for i, param_str in enumerate(param_strings):
        is_last = i == len(param_strings) - 1
        prefix = "└─ " if is_last else "├─ "
        panel_content.append_text(
            Text.assemble(
                ("\n", ThemeKey.WELCOME_INFO),
                (prefix, ThemeKey.LINES),
                (param_str, ThemeKey.WELCOME_INFO),
            )
        )

    # Render sub-agent models
    if has_sub_agents:
        # Add sub-agents header
        panel_content.append_text(
            Text.assemble(
                ("\n", ThemeKey.WELCOME_INFO),
                ("sub-agents:", ThemeKey.WELCOME_INFO),
            )
        )
        sub_agent_items = list(e.sub_agent_models.items())
        for i, (sub_agent_type, sub_llm_config) in enumerate(sub_agent_items):
            is_last = i == len(sub_agent_items) - 1
            prefix = "└─ " if is_last else "├─ "
            panel_content.append_text(
                Text.assemble(
                    ("\n", ThemeKey.WELCOME_INFO),
                    (prefix, ThemeKey.LINES),
                    (sub_agent_type.lower(), ThemeKey.WELCOME_INFO),
                    (": ", ThemeKey.LINES),
                    (str(sub_llm_config.model), ThemeKey.WELCOME_HIGHLIGHT),
                    (" @ ", ThemeKey.WELCOME_INFO),
                    (sub_llm_config.provider_name, ThemeKey.WELCOME_INFO),
                )
            )

    border_style = ThemeKey.WELCOME_DEBUG_BORDER if debug_mode else ThemeKey.LINES

    if e.show_klaude_code_info:
        groups = ["", Quote(panel_content, style=border_style, prefix="▌ "), ""]
    else:
        groups = [Quote(panel_content, style=border_style, prefix="▌ "), ""]
    return Group(*groups)