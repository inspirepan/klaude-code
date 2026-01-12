import datetime

from rich.box import HORIZONTALS
from rich.console import Console, Group
from rich.table import Table
from rich.text import Text

from klaude_code.config import Config
from klaude_code.config.config import ModelConfig, ProviderConfig, parse_env_var_syntax
from klaude_code.protocol.llm_param import LLMClientProtocol
from klaude_code.protocol.sub_agent import iter_sub_agent_profiles
from klaude_code.tui.components.rich.quote import Quote
from klaude_code.tui.components.rich.theme import ThemeKey, get_theme
from klaude_code.ui.common import format_model_params


def _get_codex_status_rows() -> list[tuple[Text, Text]]:
    """Get Codex OAuth login status as (label, value) tuples for table display."""
    from klaude_code.auth.codex.token_manager import CodexTokenManager

    rows: list[tuple[Text, Text]] = []
    token_manager = CodexTokenManager()
    state = token_manager.get_state()

    if state is None:
        rows.append(
            (
                Text("Status", style=ThemeKey.CONFIG_PARAM_LABEL),
                Text.assemble(
                    ("Not logged in", ThemeKey.CONFIG_STATUS_ERROR),
                    (" (run 'klaude login codex' to authenticate)", "dim"),
                ),
            )
        )
    elif state.is_expired():
        rows.append(
            (
                Text("Status", style=ThemeKey.CONFIG_PARAM_LABEL),
                Text.assemble(
                    ("Token expired", ThemeKey.CONFIG_STATUS_ERROR),
                    (" (run 'klaude login codex' to re-authenticate)", "dim"),
                ),
            )
        )
    else:
        expires_dt = datetime.datetime.fromtimestamp(state.expires_at, tz=datetime.UTC)
        rows.append(
            (
                Text("Status", style=ThemeKey.CONFIG_PARAM_LABEL),
                Text.assemble(
                    ("Logged in", ThemeKey.CONFIG_STATUS_OK),
                    (
                        f" (account: {state.account_id[:8]}…, expires: {expires_dt.strftime('%Y-%m-%d %H:%M UTC')})",
                        "dim",
                    ),
                ),
            )
        )

    rows.append(
        (
            Text("Usage", style="dim"),
            Text(
                "https://chatgpt.com/codex/settings/usage",
                style="blue link https://chatgpt.com/codex/settings/usage",
            ),
        )
    )
    return rows


def _get_claude_status_rows() -> list[tuple[Text, Text]]:
    """Get Claude OAuth login status as (label, value) tuples for table display."""
    from klaude_code.auth.claude.token_manager import ClaudeTokenManager

    rows: list[tuple[Text, Text]] = []
    token_manager = ClaudeTokenManager()
    state = token_manager.get_state()

    if state is None:
        rows.append(
            (
                Text("Status", style=ThemeKey.CONFIG_PARAM_LABEL),
                Text.assemble(
                    ("Not logged in", ThemeKey.CONFIG_STATUS_ERROR),
                    (" (run 'klaude login claude' to authenticate)", "dim"),
                ),
            )
        )
    elif state.is_expired():
        rows.append(
            (
                Text("Status", style=ThemeKey.CONFIG_PARAM_LABEL),
                Text.assemble(
                    ("Token expired", ThemeKey.CONFIG_STATUS_ERROR),
                    (" (will refresh automatically on use; run 'klaude login claude' if refresh fails)", "dim"),
                ),
            )
        )
    else:
        expires_dt = datetime.datetime.fromtimestamp(state.expires_at, tz=datetime.UTC)
        rows.append(
            (
                Text("Status", style=ThemeKey.CONFIG_PARAM_LABEL),
                Text.assemble(
                    ("Logged in", ThemeKey.CONFIG_STATUS_OK),
                    (f" (expires: {expires_dt.strftime('%Y-%m-%d %H:%M UTC')})", "dim"),
                ),
            )
        )

    rows.append(
        (
            Text("Usage", style="dim"),
            Text(
                "https://claude.ai/settings/usage",
                style="blue link https://claude.ai/settings/usage",
            ),
        )
    )
    return rows


def _get_antigravity_status_rows() -> list[tuple[Text, Text]]:
    """Get Antigravity OAuth login status as (label, value) tuples for table display."""
    from klaude_code.auth.antigravity.token_manager import AntigravityTokenManager

    rows: list[tuple[Text, Text]] = []
    token_manager = AntigravityTokenManager()
    state = token_manager.get_state()

    if state is None:
        rows.append(
            (
                Text("Status", style=ThemeKey.CONFIG_PARAM_LABEL),
                Text.assemble(
                    ("Not logged in", ThemeKey.CONFIG_STATUS_ERROR),
                    (" (run 'klaude login antigravity' to authenticate)", "dim"),
                ),
            )
        )
    elif state.is_expired():
        rows.append(
            (
                Text("Status", style=ThemeKey.CONFIG_PARAM_LABEL),
                Text.assemble(
                    ("Token expired", ThemeKey.CONFIG_STATUS_ERROR),
                    (" (will refresh automatically on use; run 'klaude login antigravity' if refresh fails)", "dim"),
                ),
            )
        )
    else:
        expires_dt = datetime.datetime.fromtimestamp(state.expires_at, tz=datetime.UTC)
        email_info = f", email: {state.email}" if state.email else ""
        rows.append(
            (
                Text("Status", style=ThemeKey.CONFIG_PARAM_LABEL),
                Text.assemble(
                    ("Logged in", ThemeKey.CONFIG_STATUS_OK),
                    (
                        f" (project: {state.project_id}{email_info}, expires: {expires_dt.strftime('%Y-%m-%d %H:%M UTC')})",
                        "dim",
                    ),
                ),
            )
        )

    return rows


def mask_api_key(api_key: str | None) -> str:
    """Mask API key to show only first 6 and last 6 characters with *** in between"""
    if not api_key:
        return ""

    if len(api_key) <= 12:
        return api_key

    return f"{api_key[:6]}…{api_key[-6:]}"


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
        return Text("")


def format_env_var_display(value: str | None) -> Text:
    """Format environment variable display with warning if not set."""
    env_var, resolved = parse_env_var_syntax(value)

    if env_var:
        # Using ${ENV_VAR} syntax
        if resolved:
            return Text.assemble(
                (f"${{{env_var}}} = ", "dim"),
                (mask_api_key(resolved), ""),
            )
        else:
            return Text.assemble(
                (f"${{{env_var}}} ", ""),
                ("(not set)", ThemeKey.CONFIG_STATUS_ERROR),
            )
    elif value:
        # Plain value
        return Text(mask_api_key(value))
    else:
        return Text("")


def _get_model_params_display(model: ModelConfig) -> list[Text]:
    """Get display elements for model parameters."""
    param_strings = format_model_params(model)
    if param_strings:
        return [Text(s) for s in param_strings]
    return [Text("")]


def _build_provider_info_panel(provider: ProviderConfig, available: bool, *, disabled: bool) -> Quote:
    """Build a Quote containing provider name and information using a two-column grid."""
    # Provider name as title
    if disabled:
        title = Text.assemble(
            (provider.provider_name, ThemeKey.CONFIG_PROVIDER),
            (" (Disabled)", "dim"),
        )
    elif available:
        title = Text(provider.provider_name, style=ThemeKey.CONFIG_PROVIDER)
    else:
        title = Text.assemble(
            (provider.provider_name, ThemeKey.CONFIG_PROVIDER),
            (" (Unavailable)", ThemeKey.CONFIG_STATUS_ERROR),
        )

    # Build info table with two columns
    info_table = Table.grid(padding=(0, 2))
    info_table.add_column("Label", style=ThemeKey.CONFIG_PARAM_LABEL)
    info_table.add_column("Value")

    # Protocol
    info_table.add_row(Text("Protocol"), Text(provider.protocol.value))

    # Base URL (if set)
    if provider.base_url:
        info_table.add_row(Text("Base URL"), Text(provider.base_url))

    # API key (if set)
    if provider.api_key:
        info_table.add_row(Text("API key"), format_api_key_display(provider))

    # AWS Bedrock parameters
    if provider.protocol == LLMClientProtocol.BEDROCK:
        if provider.aws_access_key:
            info_table.add_row(Text("AWS key"), format_env_var_display(provider.aws_access_key))
        if provider.aws_secret_key:
            info_table.add_row(Text("AWS secret"), format_env_var_display(provider.aws_secret_key))
        if provider.aws_region:
            info_table.add_row(Text("AWS region"), format_env_var_display(provider.aws_region))
        if provider.aws_session_token:
            info_table.add_row(Text("AWS token"), format_env_var_display(provider.aws_session_token))
        if provider.aws_profile:
            info_table.add_row(Text("AWS profile"), format_env_var_display(provider.aws_profile))

    # OAuth status rows
    if provider.protocol == LLMClientProtocol.CODEX_OAUTH:
        for label, value in _get_codex_status_rows():
            info_table.add_row(label, value)
    if provider.protocol == LLMClientProtocol.CLAUDE_OAUTH:
        for label, value in _get_claude_status_rows():
            info_table.add_row(label, value)
    if provider.protocol == LLMClientProtocol.ANTIGRAVITY:
        for label, value in _get_antigravity_status_rows():
            info_table.add_row(label, value)

    return Quote(
        Group(title, info_table),
        style=ThemeKey.LINES,
        prefix="┃ ",
    )


def _build_models_table(
    provider: ProviderConfig,
    config: Config,
) -> Table:
    """Build a table for models under a provider."""
    provider_disabled = provider.disabled
    provider_available = (not provider_disabled) and (not provider.is_api_key_missing())

    def _resolve_selector(value: str | None) -> str | None:
        if not value:
            return None
        try:
            resolved = config.resolve_model_location_prefer_available(value) or config.resolve_model_location(value)
        except ValueError:
            return None
        if resolved is None:
            return None
        return f"{resolved[0]}@{resolved[1]}"

    default_selector = _resolve_selector(config.main_model)

    # Build reverse mapping: model_name -> list of agent roles using it
    model_to_agents: dict[str, list[str]] = {}
    for agent_role, model_name in (config.sub_agent_models or {}).items():
        selector = _resolve_selector(model_name)
        if selector is None:
            continue
        if selector not in model_to_agents:
            model_to_agents[selector] = []
        model_to_agents[selector].append(agent_role)

    models_table = Table.grid(
        padding=(0, 2),
    )
    models_table.add_column("Model Name", min_width=12)
    models_table.add_column("Model ID", min_width=20, style=ThemeKey.CONFIG_MODEL_ID)
    models_table.add_column("Params", style="dim")

    model_count = len(provider.model_list)
    for i, model in enumerate(provider.model_list):
        is_last = i == model_count - 1
        prefix = " ╰─ " if is_last else " ├─ "

        if provider_disabled:
            name = Text.assemble(
                (prefix, ThemeKey.LINES),
                (model.model_name, "dim strike"),
                (" (provider disabled)", "dim"),
            )
            model_id = Text(model.model_id or "", style="dim")
            params = Text("(disabled)", style="dim")
        elif not provider_available:
            name = Text.assemble((prefix, ThemeKey.LINES), (model.model_name, "dim"))
            model_id = Text(model.model_id or "", style="dim")
            params = Text("(unavailable)", style="dim")
        elif model.disabled:
            name = Text.assemble(
                (prefix, ThemeKey.LINES),
                (model.model_name, "dim strike"),
                (" (disabled)", "dim"),
            )
            model_id = Text(model.model_id or "", style="dim")
            params = Text(" · ").join(_get_model_params_display(model))
        else:
            # Build role tags for this model
            roles: list[str] = []
            selector = f"{model.model_name}@{provider.provider_name}"
            if selector == default_selector:
                roles.append("default")
            if selector in model_to_agents:
                roles.extend(role.lower() for role in model_to_agents[selector])

            if roles:
                name = Text.assemble(
                    (prefix, ThemeKey.LINES),
                    (model.model_name, ThemeKey.CONFIG_STATUS_PRIMARY),
                    (f" ({', '.join(roles)})", "dim"),
                )
            else:
                name = Text.assemble((prefix, ThemeKey.LINES), (model.model_name, ThemeKey.CONFIG_ITEM_NAME))
            model_id = Text(model.model_id or "")
            params = Text(" · ").join(_get_model_params_display(model))

        models_table.add_row(name, model_id, params)

    return models_table


def _display_agent_models_table(config: Config, console: Console) -> None:
    """Display model assignments as a table."""
    console.print(Text(" Agent Models:", style=ThemeKey.CONFIG_TABLE_HEADER))
    agent_table = Table(
        box=HORIZONTALS,
        show_header=True,
        header_style=ThemeKey.CONFIG_TABLE_HEADER,
        padding=(0, 2),
        border_style=ThemeKey.LINES,
    )
    agent_table.add_column("Role", style="bold", min_width=10)
    agent_table.add_column("Model", style=ThemeKey.CONFIG_STATUS_PRIMARY)

    # Default model
    if config.main_model:
        agent_table.add_row("Default", config.main_model)
    else:
        agent_table.add_row("Default", Text("(not set)", style=ThemeKey.CONFIG_STATUS_ERROR))

    # Sub-agent models
    for profile in iter_sub_agent_profiles():
        sub_model_name = config.sub_agent_models.get(profile.name)
        if sub_model_name:
            agent_table.add_row(profile.name, sub_model_name)

    console.print(agent_table)


def display_models_and_providers(config: Config, *, show_all: bool = False):
    """Display models and providers configuration using rich formatting"""
    themes = get_theme(config.theme)
    console = Console(theme=themes.app_theme)

    # Display model assignments as a table
    _display_agent_models_table(config, console)
    console.print()

    # Sort providers: enabled+available first, disabled/unavailable last
    sorted_providers = sorted(
        config.provider_list,
        key=lambda p: (p.disabled, p.is_api_key_missing(), p.provider_name),
    )

    # Filter out disabled/unavailable providers unless show_all is True
    if not show_all:
        sorted_providers = [p for p in sorted_providers if (not p.disabled) and (not p.is_api_key_missing())]

    # Display each provider with its models table
    for provider in sorted_providers:
        provider_available = (not provider.disabled) and (not provider.is_api_key_missing())

        # Provider info panel
        provider_panel = _build_provider_info_panel(provider, provider_available, disabled=provider.disabled)
        console.print(provider_panel)

        # Models table for this provider
        models_table = _build_models_table(provider, config)
        console.print(models_table)
        console.print("\n")
