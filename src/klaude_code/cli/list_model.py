import datetime

from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from klaude_code.config import Config
from klaude_code.config.config import ModelConfig, ProviderConfig
from klaude_code.protocol.llm_param import LLMClientProtocol
from klaude_code.protocol.sub_agent import iter_sub_agent_profiles
from klaude_code.ui.rich.theme import ThemeKey, get_theme


def _get_codex_status_elements() -> list[Text]:
    """Get Codex OAuth login status as Text elements for panel display."""
    from klaude_code.auth.codex.token_manager import CodexTokenManager

    elements: list[Text] = []
    token_manager = CodexTokenManager()
    state = token_manager.get_state()

    if state is None:
        elements.append(
            Text.assemble(
                ("Status: ", "bold"),
                ("Not logged in", ThemeKey.CONFIG_STATUS_ERROR),
                (" (run 'klaude login codex' to authenticate)", "dim"),
            )
        )
    elif state.is_expired():
        elements.append(
            Text.assemble(
                ("Status: ", "bold"),
                ("Token expired", ThemeKey.CONFIG_STATUS_ERROR),
                (" (run 'klaude login codex' to re-authenticate)", "dim"),
            )
        )
    else:
        expires_dt = datetime.datetime.fromtimestamp(state.expires_at, tz=datetime.UTC)
        elements.append(
            Text.assemble(
                ("Status: ", "bold"),
                ("Logged in", ThemeKey.CONFIG_STATUS_OK),
                (f" (account: {state.account_id[:8]}..., expires: {expires_dt.strftime('%Y-%m-%d %H:%M UTC')})", "dim"),
            )
        )

    elements.append(
        Text.assemble(
            ("Visit ", "dim"),
            (
                "https://chatgpt.com/codex/settings/usage",
                "blue underline link https://chatgpt.com/codex/settings/usage",
            ),
            (" for up-to-date information on rate limits and credits", "dim"),
        )
    )
    return elements


def mask_api_key(api_key: str | None) -> str:
    """Mask API key to show only first 6 and last 6 characters with *** in between"""
    if not api_key or api_key == "N/A":
        return "N/A"

    if len(api_key) <= 12:
        return api_key

    return f"{api_key[:6]} … {api_key[-6:]}"


def format_api_key_display(provider: ProviderConfig) -> Text:
    """Format API key display with warning if env var is not set."""
    env_var = provider.get_api_key_env_var()
    resolved_key = provider.get_resolved_api_key()

    if env_var:
        # Using ${ENV_VAR} syntax
        if resolved_key:
            return Text.assemble(
                (f"${{{env_var}}} = ", "dim"),
                (mask_api_key(resolved_key), ""),
            )
        else:
            return Text.assemble(
                (f"${{{env_var}}} ", ""),
                ("(not set)", ThemeKey.CONFIG_STATUS_ERROR),
            )
    elif provider.api_key:
        # Plain API key
        return Text(mask_api_key(provider.api_key))
    else:
        return Text("N/A")


def _get_model_params_display(model: ModelConfig) -> list[Text]:
    """Get display elements for model parameters."""
    params: list[Text] = []
    if model.model_params.thinking:
        if model.model_params.thinking.reasoning_effort is not None:
            params.append(
                Text.assemble(
                    ("reason-effort", ThemeKey.CONFIG_PARAM_LABEL),
                    ": ",
                    model.model_params.thinking.reasoning_effort,
                )
            )
        if model.model_params.thinking.reasoning_summary is not None:
            params.append(
                Text.assemble(
                    ("reason-summary", ThemeKey.CONFIG_PARAM_LABEL),
                    ": ",
                    model.model_params.thinking.reasoning_summary,
                )
            )
        if model.model_params.thinking.budget_tokens is not None:
            params.append(
                Text.assemble(
                    ("thinking-budget-tokens", ThemeKey.CONFIG_PARAM_LABEL),
                    ": ",
                    str(model.model_params.thinking.budget_tokens),
                )
            )
    if model.model_params.provider_routing:
        params.append(
            Text.assemble(
                ("provider-routing", ThemeKey.CONFIG_PARAM_LABEL),
                ": ",
                model.model_params.provider_routing.model_dump_json(exclude_none=True),
            )
        )
    if len(params) == 0:
        params.append(Text("N/A", style=ThemeKey.CONFIG_PARAM_LABEL))
    return params


def display_models_and_providers(config: Config):
    """Display models and providers configuration using rich formatting"""
    themes = get_theme(config.theme)
    console = Console(theme=themes.app_theme)

    # Display each provider as a separate panel
    for provider in config.provider_list:
        # Provider info section
        provider_info = Table.grid(padding=(0, 1))
        provider_info.add_column(width=12)
        provider_info.add_column()

        provider_info.add_row(
            Text("Protocol:", style=ThemeKey.CONFIG_PARAM_LABEL),
            Text(provider.protocol.value),
        )
        if provider.base_url:
            provider_info.add_row(
                Text("Base URL:", style=ThemeKey.CONFIG_PARAM_LABEL),
                Text(provider.base_url or "N/A"),
            )
        if provider.api_key:
            provider_info.add_row(
                Text("API Key:", style=ThemeKey.CONFIG_PARAM_LABEL),
                format_api_key_display(provider),
            )

        # Check if provider has valid API key
        provider_available = not provider.is_api_key_missing()

        # Models table for this provider
        models_table = Table.grid(padding=(0, 1), expand=True)
        models_table.add_column(width=2, no_wrap=True)  # Status
        models_table.add_column(overflow="fold", ratio=1)  # Name
        models_table.add_column(overflow="fold", ratio=2)  # Model
        models_table.add_column(overflow="fold", ratio=3)  # Params

        # Add header
        models_table.add_row(
            Text("", style="bold"),
            Text("Name", style=ThemeKey.CONFIG_TABLE_HEADER),
            Text("Model", style=ThemeKey.CONFIG_TABLE_HEADER),
            Text("Params", style=ThemeKey.CONFIG_TABLE_HEADER),
        )

        # Add models for this provider
        for model in provider.model_list:
            if not provider_available:
                # Provider API key not set - show as unavailable
                status = Text("-", style="dim")
                name = Text(model.model_name, style="dim")
                model_id = Text(model.model_params.model or "N/A", style="dim")
                params = [Text("(unavailable)", style="dim")]
            elif model.model_name == config.main_model:
                status = Text("★", style=ThemeKey.CONFIG_STATUS_PRIMARY)
                name = Text(model.model_name, style=ThemeKey.CONFIG_STATUS_PRIMARY)
                model_id = Text(model.model_params.model or "N/A", style="")
                params = _get_model_params_display(model)
            else:
                status = Text("✔", style=ThemeKey.CONFIG_STATUS_OK)
                name = Text(model.model_name, style=ThemeKey.CONFIG_ITEM_NAME)
                model_id = Text(model.model_params.model or "N/A", style="")
                params = _get_model_params_display(model)

            models_table.add_row(status, name, model_id, Group(*params))

        # Create panel content with provider info and models
        panel_elements = [
            provider_info,
            Text(""),  # Spacer
            Text("Models:", style=ThemeKey.CONFIG_TABLE_HEADER),
            models_table,
        ]

        # Add Codex status if this is a codex provider
        if provider.protocol == LLMClientProtocol.CODEX:
            panel_elements.append(Text(""))  # Spacer
            panel_elements.extend(_get_codex_status_elements())

        panel_content = Group(*panel_elements)

        panel = Panel(
            panel_content,
            title=Text(f"Provider: {provider.provider_name}", style=ThemeKey.CONFIG_PROVIDER),
            border_style=ThemeKey.CONFIG_PANEL_BORDER,
            padding=(0, 1),
            title_align="left",
        )

        console.print(panel)
        console.print()

    # Display main model info
    console.print()
    if config.main_model:
        console.print(
            Text.assemble(
                ("Default Model: ", "bold"),
                (config.main_model, ThemeKey.CONFIG_STATUS_PRIMARY),
            )
        )
    else:
        console.print(
            Text.assemble(
                ("Default Model: ", "bold"),
                ("(not set)", ThemeKey.CONFIG_STATUS_ERROR),
            )
        )

    for profile in iter_sub_agent_profiles():
        sub_model_name = config.sub_agent_models.get(profile.name)
        if not sub_model_name:
            continue
        console.print(
            Text.assemble(
                (f"{profile.name} Model: ", "bold"),
                (sub_model_name, ThemeKey.CONFIG_STATUS_PRIMARY),
            )
        )
