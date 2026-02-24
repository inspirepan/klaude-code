import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import ClassVar

from rich.box import HORIZONTALS
from rich.console import Console, Group
from rich.padding import Padding
from rich.table import Table
from rich.text import Text
from rich.tree import Tree

from klaude_code.cli.oauth_usage import (
    format_oauth_usage_summary,
    load_oauth_usage_summary,
    resolve_oauth_usage_protocol,
)
from klaude_code.config import Config
from klaude_code.config.config import ModelConfig, ProviderConfig, parse_env_var_syntax
from klaude_code.protocol.llm_param import LLMClientProtocol
from klaude_code.protocol.sub_agent import iter_sub_agent_profiles
from klaude_code.tui.components.rich.quote import Quote
from klaude_code.tui.components.rich.theme import ThemeKey, get_theme
from klaude_code.ui.common import format_model_params


class _RoundedTree(Tree):
    TREE_GUIDES: ClassVar[list[tuple[str, str, str, str]]] = [
        ("    ", "│   ", "├── ", "╰── "),
        ("    ", "│   ", "├── ", "╰── "),
        ("    ", "│   ", "├── ", "╰── "),
    ]


def _append_usage_suffix(value: Text, usage_summary: str | None) -> Text:
    if not usage_summary:
        return value
    out = value.copy()
    out.append(f" · usage: {usage_summary}", style="blue")
    return out


def _get_codex_status_rows(*, usage_summary: str | None = None) -> list[tuple[Text, Text]]:
    """Get Codex OAuth login status as (label, value) tuples for table display."""
    from klaude_code.auth.codex.token_manager import CodexTokenManager

    rows: list[tuple[Text, Text]] = []
    token_manager = CodexTokenManager()
    state = token_manager.get_state()

    if state is None:
        rows.append(
            (
                Text("Status", style=ThemeKey.CONFIG_PARAM_LABEL),
                _append_usage_suffix(
                    Text.assemble(
                        ("Not logged in", ThemeKey.CONFIG_STATUS_ERROR),
                        (" (run 'klaude auth login codex' to authenticate)", "dim"),
                    ),
                    usage_summary,
                ),
            )
        )
    elif state.is_expired():
        rows.append(
            (
                Text("Status", style=ThemeKey.CONFIG_PARAM_LABEL),
                _append_usage_suffix(
                    Text.assemble(
                        ("Token expired", ThemeKey.CONFIG_STATUS_ERROR),
                        (" (run 'klaude auth login codex' to re-authenticate)", "dim"),
                    ),
                    usage_summary,
                ),
            )
        )
    else:
        expires_dt = datetime.datetime.fromtimestamp(state.expires_at, tz=datetime.UTC)
        rows.append(
            (
                Text("Status", style=ThemeKey.CONFIG_PARAM_LABEL),
                _append_usage_suffix(
                    Text.assemble(
                        ("Logged in", ThemeKey.CONFIG_STATUS_OK),
                        (
                            f" (account: {state.account_id[:8]}…, expires: {expires_dt.strftime('%Y-%m-%d %H:%M UTC')})",
                            "dim",
                        ),
                    ),
                    usage_summary,
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


def _get_claude_status_rows(*, usage_summary: str | None = None) -> list[tuple[Text, Text]]:
    """Get Claude OAuth login status as (label, value) tuples for table display."""
    from klaude_code.auth.claude.token_manager import ClaudeTokenManager

    rows: list[tuple[Text, Text]] = []
    token_manager = ClaudeTokenManager()
    state = token_manager.get_state()

    if state is None:
        rows.append(
            (
                Text("Status", style=ThemeKey.CONFIG_PARAM_LABEL),
                _append_usage_suffix(
                    Text.assemble(
                        ("Not logged in", ThemeKey.CONFIG_STATUS_ERROR),
                        (" (run 'klaude auth login claude' to authenticate)", "dim"),
                    ),
                    usage_summary,
                ),
            )
        )
    elif state.is_expired():
        rows.append(
            (
                Text("Status", style=ThemeKey.CONFIG_PARAM_LABEL),
                _append_usage_suffix(
                    Text.assemble(
                        ("Token expired", ThemeKey.CONFIG_STATUS_ERROR),
                        (
                            " (will refresh automatically on use; run 'klaude auth login claude' if refresh fails)",
                            "dim",
                        ),
                    ),
                    usage_summary,
                ),
            )
        )
    else:
        expires_dt = datetime.datetime.fromtimestamp(state.expires_at, tz=datetime.UTC)
        rows.append(
            (
                Text("Status", style=ThemeKey.CONFIG_PARAM_LABEL),
                _append_usage_suffix(
                    Text.assemble(
                        ("Logged in", ThemeKey.CONFIG_STATUS_OK),
                        (f" (expires: {expires_dt.strftime('%Y-%m-%d %H:%M UTC')})", "dim"),
                    ),
                    usage_summary,
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


def _get_copilot_status_rows(*, usage_summary: str | None = None) -> list[tuple[Text, Text]]:
    """Get Copilot OAuth login status as (label, value) tuples for table display."""
    from klaude_code.auth.copilot.token_manager import CopilotTokenManager

    rows: list[tuple[Text, Text]] = []
    token_manager = CopilotTokenManager()
    state = token_manager.get_state()

    if state is None:
        rows.append(
            (
                Text("Status", style=ThemeKey.CONFIG_PARAM_LABEL),
                _append_usage_suffix(
                    Text.assemble(
                        ("Not logged in", ThemeKey.CONFIG_STATUS_ERROR),
                        (" (run 'klaude auth login copilot' to authenticate)", "dim"),
                    ),
                    usage_summary,
                ),
            )
        )
    elif state.is_expired():
        rows.append(
            (
                Text("Status", style=ThemeKey.CONFIG_PARAM_LABEL),
                _append_usage_suffix(
                    Text.assemble(
                        ("Token expired", ThemeKey.CONFIG_STATUS_ERROR),
                        (" (run 'klaude auth login copilot' to re-authenticate)", "dim"),
                    ),
                    usage_summary,
                ),
            )
        )
    else:
        expires_dt = datetime.datetime.fromtimestamp(state.expires_at, tz=datetime.UTC)
        domain = state.enterprise_domain or "github.com"
        rows.append(
            (
                Text("Status", style=ThemeKey.CONFIG_PARAM_LABEL),
                _append_usage_suffix(
                    Text.assemble(
                        ("Logged in", ThemeKey.CONFIG_STATUS_OK),
                        (f" (domain: {domain}, expires: {expires_dt.strftime('%Y-%m-%d %H:%M UTC')})", "dim"),
                    ),
                    usage_summary,
                ),
            )
        )

    rows.append(
        (
            Text("Usage", style="dim"),
            Text(
                "https://github.com/settings/copilot",
                style="blue link https://github.com/settings/copilot",
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
                (mask_api_key(resolved_key), ThemeKey.CONFIG_PARAM_VALUE),
            )
        else:
            return Text.assemble(
                (f"${{{env_var}}} ", ""),
                ("(not set)", ThemeKey.CONFIG_STATUS_ERROR),
            )
    elif provider.api_key:
        # Plain API key
        return Text(mask_api_key(provider.api_key), style=ThemeKey.CONFIG_PARAM_VALUE)
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
                (mask_api_key(resolved), ThemeKey.CONFIG_PARAM_VALUE),
            )
        else:
            return Text.assemble(
                (f"${{{env_var}}} ", ""),
                ("(not set)", ThemeKey.CONFIG_STATUS_ERROR),
            )
    elif value:
        # Plain value
        return Text(mask_api_key(value), style=ThemeKey.CONFIG_PARAM_VALUE)
    else:
        return Text("")


def _get_model_params_display(model: ModelConfig) -> list[Text]:
    """Get display elements for model parameters."""
    param_strings = format_model_params(model)
    if param_strings:
        return [Text(s, style=ThemeKey.CONFIG_PARAM_LABEL) for s in param_strings]
    return [Text("", style=ThemeKey.CONFIG_PARAM_LABEL)]


def _pad_text_right(text: Text, width: int) -> Text:
    """Pad rich Text to a fixed display width (monospace cells)."""
    out = text.copy()
    pad = max(0, width - out.cell_len)
    if pad:
        out.append(" " * pad)
    return out


def _build_provider_info_panel(
    provider: ProviderConfig,
    available: bool,
    *,
    disabled: bool,
    oauth_usage_by_protocol: dict[LLMClientProtocol, str],
) -> Quote:
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
    info_table.add_column("Value", style=ThemeKey.CONFIG_PARAM_VALUE)

    # Protocol
    info_table.add_row(Text("Protocol"), Text(provider.protocol.value, style=ThemeKey.CONFIG_PARAM_VALUE))

    # Base URL (if set)
    if provider.base_url:
        info_table.add_row(Text("Base URL"), Text(provider.base_url, style=ThemeKey.CONFIG_PARAM_VALUE))

    # API key (if set)
    if provider.api_key:
        info_table.add_row(Text("API Key"), format_api_key_display(provider))

    # AWS Bedrock parameters
    if provider.protocol == LLMClientProtocol.BEDROCK:
        if provider.aws_access_key:
            info_table.add_row(Text("AWS Access Key"), format_env_var_display(provider.aws_access_key))
        if provider.aws_secret_key:
            info_table.add_row(Text("AWS Secret Key"), format_env_var_display(provider.aws_secret_key))
        if provider.aws_region:
            info_table.add_row(Text("AWS Region"), format_env_var_display(provider.aws_region))
        if provider.aws_session_token:
            info_table.add_row(Text("AWS Session Token"), format_env_var_display(provider.aws_session_token))
        if provider.aws_profile:
            info_table.add_row(Text("AWS Profile"), format_env_var_display(provider.aws_profile))

    if provider.protocol == LLMClientProtocol.GOOGLE_VERTEX:
        if provider.google_application_credentials:
            info_table.add_row(
                Text("Google Application Credentials"),
                format_env_var_display(provider.google_application_credentials),
            )
        if provider.google_cloud_project:
            info_table.add_row(Text("Google Cloud Project"), format_env_var_display(provider.google_cloud_project))
        if provider.google_cloud_location:
            info_table.add_row(Text("Google Cloud Location"), format_env_var_display(provider.google_cloud_location))

    # OAuth status rows
    usage_summary = oauth_usage_by_protocol.get(provider.protocol)
    if provider.protocol == LLMClientProtocol.CODEX_OAUTH:
        for label, value in _get_codex_status_rows(usage_summary=usage_summary):
            info_table.add_row(label, value)
    if provider.protocol == LLMClientProtocol.CLAUDE_OAUTH:
        for label, value in _get_claude_status_rows(usage_summary=usage_summary):
            info_table.add_row(label, value)
    if provider.protocol == LLMClientProtocol.COPILOT_OAUTH:
        for label, value in _get_copilot_status_rows(usage_summary=usage_summary):
            info_table.add_row(label, value)

    return Quote(
        Group(title, info_table),
        style=ThemeKey.LINES,
        prefix="┃ ",
    )


def _build_models_tree(
    provider: ProviderConfig,
    config: Config,
) -> Tree:
    """Build a tree for models under a provider."""
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

    models_tree = _RoundedTree(Text("Models", style=ThemeKey.CONFIG_PARAM_LABEL), guide_style=ThemeKey.LINES)

    model_rows: list[tuple[Text, Text, Text | None, Text | None]] = []

    for model in provider.model_list:
        params: Text | None = None

        if provider_disabled:
            name = Text.assemble(
                (model.model_name, "dim strike"),
                (" (provider disabled)", "dim"),
            )
            model_id = Text(model.model_id or "", style="dim")
            status = Text("status: disabled", style="dim")
        elif not provider_available:
            name = Text(model.model_name, style="dim")
            model_id = Text(model.model_id or "", style="dim")
            status = Text("status: unavailable", style="dim")
        elif model.disabled:
            name = Text.assemble(
                (model.model_name, "dim strike"),
                (" (disabled)", "dim"),
            )
            model_id = Text(model.model_id or "", style="dim")
            status = Text("status: disabled", style="dim")
            params = Text(" · ").join(_get_model_params_display(model))
        else:
            # Build role tags for this model
            roles: list[str] = []
            selector = f"{model.model_name}@{provider.provider_name}"
            if selector == default_selector:
                roles.append("default")
            if selector in model_to_agents:
                roles.extend(role.lower() for role in model_to_agents[selector])

            name = Text()
            if roles:
                name.append(model.model_name, style=ThemeKey.CONFIG_STATUS_PRIMARY)
                name.append(f" ({', '.join(roles)})", style="dim")
            else:
                name.append(model.model_name, style=ThemeKey.CONFIG_ITEM_NAME)
            model_id = Text(model.model_id or "", style=ThemeKey.CONFIG_MODEL_ID)
            params = Text(" · ").join(_get_model_params_display(model))
            status = None

        model_rows.append((name, model_id, status, params))

    name_width = max((name.cell_len for name, _, _, _ in model_rows), default=0)

    for name, model_id, status, params in model_rows:
        model_line = _pad_text_right(name, name_width)

        if model_id.plain:
            model_line.append(" → ", style="dim")
            model_line.append_text(model_id)

        if provider_available and (not provider_disabled) and params is not None and params.plain:
            model_line.append(" · ", style="dim")
            model_line.append_text(params)

        if status is not None:
            model_line.append(" · ", style="dim")
            model_line.append_text(status)

        models_tree.add(model_line)

    return models_tree


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

    def _print_provider(provider: ProviderConfig, usage_map: dict[LLMClientProtocol, str]) -> None:
        provider_available = (not provider.disabled) and (not provider.is_api_key_missing())

        # Provider info panel
        provider_panel = _build_provider_info_panel(
            provider,
            provider_available,
            disabled=provider.disabled,
            oauth_usage_by_protocol=usage_map,
        )
        console.print(provider_panel)

        # Models tree for this provider
        models_tree = _build_models_tree(provider, config)
        console.print(Padding(models_tree, (0, 0, 0, 2)))
        console.print("\n")

    oauth_provider_groups: dict[LLMClientProtocol, list[ProviderConfig]] = {}
    non_oauth_providers: list[ProviderConfig] = []

    for provider in sorted_providers:
        usage_protocol = resolve_oauth_usage_protocol(provider.protocol)
        if usage_protocol is None:
            non_oauth_providers.append(provider)
        else:
            oauth_provider_groups.setdefault(usage_protocol, []).append(provider)

    # Non-OAuth providers are printed immediately.
    for provider in non_oauth_providers:
        _print_provider(provider, usage_map={})

    # OAuth providers are printed as soon as their usage snapshot is loaded.
    if oauth_provider_groups:
        with ThreadPoolExecutor(max_workers=min(len(oauth_provider_groups), 3)) as executor:
            future_to_protocol = {
                executor.submit(load_oauth_usage_summary, protocols={protocol}, timeout_seconds=3.5): protocol
                for protocol in oauth_provider_groups
            }

            for future in as_completed(future_to_protocol):
                protocol = future_to_protocol[future]
                usage_map: dict[LLMClientProtocol, str] = {}
                try:
                    snapshots = future.result()
                    snapshot = snapshots.get(protocol)
                    if snapshot is not None:
                        usage_summary = format_oauth_usage_summary(snapshot, max_windows=2)
                        if usage_summary:
                            usage_map[protocol] = usage_summary
                except Exception:
                    # Usage display must never break `klaude list`.
                    usage_map = {}

                for provider in oauth_provider_groups.get(protocol, []):
                    _print_provider(provider, usage_map)
