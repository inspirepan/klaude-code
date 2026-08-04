import os
from concurrent.futures import ThreadPoolExecutor, as_completed

from rich.console import Console
from rich.text import Text

from klaude_code.auth.env import get_auth_env
from klaude_code.cli.oauth_usage import (
    format_oauth_usage_summary,
    load_oauth_usage_summary,
    resolve_oauth_usage_protocol,
)
from klaude_code.config import Config
from klaude_code.config.config import ModelConfig, ModelPreference, ProviderConfig, parse_env_var_syntax
from klaude_code.config.formatters import format_model_params
from klaude_code.protocol.llm_param import LLMClientProtocol
from klaude_code.tui.components.rich.theme import ThemeKey, get_theme


def mask_api_key(api_key: str | None) -> str:
    """Mask API key to show only first 6 and last 6 characters with *** in between"""
    if not api_key:
        return ""

    if len(api_key) <= 12:
        return api_key

    return f"{api_key[:6]}…{api_key[-6:]}"


def _resolve_env_var_source(env_var_expression: str) -> str | None:
    """Return 'env' if the value comes from os.environ, 'configured' if from auth store."""
    for env_var_name in env_var_expression.split("|"):
        if os.environ.get(env_var_name):
            return "env"
        if get_auth_env(env_var_name):
            return "configured"
    return None


def _format_secret_value_display(value: str | None, *, fallback_name: str) -> Text:
    """Format `${ENV}` or raw secret as `NAME=masked`.

    For `${A|B}` syntax, keep the expression as-is to show fallback order.
    """
    env_var, resolved = parse_env_var_syntax(value)

    if env_var:
        if resolved:
            source = _resolve_env_var_source(env_var)
            source_label = " (env)" if source == "env" else " (configured)" if source == "configured" else ""
            return Text.assemble(
                (f"{env_var}=", "dim"),
                (mask_api_key(resolved), ThemeKey.CONFIG_PARAM_VALUE),
                (source_label, "dim"),
            )
        return Text.assemble((f"{env_var}=", "dim"), ("(not set)", ThemeKey.CONFIG_STATUS_ERROR))
    if value:
        return Text.assemble((f"{fallback_name}=", "dim"), (mask_api_key(value), ThemeKey.CONFIG_PARAM_VALUE))
    return Text("")


def _format_aws_credentials_display(provider: ProviderConfig) -> list[Text]:
    """Format AWS Bedrock credentials display for provider header."""
    parts: list[Text] = []
    for field, label in (
        (provider.aws_access_key, "AWS_BEDROCK_ACCESS_KEY_ID"),
        (provider.aws_secret_key, "AWS_BEDROCK_SECRET_ACCESS_KEY"),
        (provider.aws_region, "AWS_BEDROCK_REGION"),
    ):
        display = _format_secret_value_display(field, fallback_name=label)
        if display.plain:
            parts.append(display)
    return parts


def _format_google_vertex_credentials_display(provider: ProviderConfig) -> list[Text]:
    """Format Google Vertex credentials display for provider header."""
    parts: list[Text] = []
    for field, label in (
        (provider.google_cloud_project, "GOOGLE_CLOUD_PROJECT"),
        (provider.google_cloud_location, "GOOGLE_CLOUD_LOCATION"),
    ):
        display = _format_secret_value_display(field, fallback_name=label)
        if display.plain:
            parts.append(display)
    return parts


def _build_provider_header(
    provider: ProviderConfig,
    *,
    oauth_usage_by_protocol: dict[LLMClientProtocol, str],
) -> Text:
    """Build single-line provider summary shown above the model tree."""
    provider_available = (not provider.disabled) and (not provider.is_api_key_missing())

    header = Text()
    header.append(provider.provider_name, style=ThemeKey.CONFIG_PROVIDER)

    details: list[Text] = []
    usage_summary = oauth_usage_by_protocol.get(provider.protocol)
    usage_protocol = resolve_oauth_usage_protocol(provider.protocol)

    if usage_protocol is not None:
        details.append(Text("auth", style=ThemeKey.CONFIG_PARAM_LABEL))
        if usage_summary:
            details.append(Text(f"usage: {usage_summary}", style="blue"))
    elif provider.protocol == LLMClientProtocol.BEDROCK:
        details.extend(_format_aws_credentials_display(provider))
    elif provider.protocol == LLMClientProtocol.GOOGLE_VERTEX:
        details.extend(_format_google_vertex_credentials_display(provider))
    else:
        api_key_display = _format_secret_value_display(provider.api_key, fallback_name="API_KEY")
        if api_key_display.plain:
            details.append(api_key_display)

    if provider.disabled:
        details.append(Text("disabled", style="dim"))
    elif not provider_available:
        details.append(Text("unavailable", style=ThemeKey.CONFIG_STATUS_ERROR))

    for detail in details:
        header.append(" · ", style="dim")
        header.append_text(detail)

    return header


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


def _build_model_rows(
    provider: ProviderConfig,
    config: Config,
) -> list[tuple[Text, Text, Text]]:
    """Build (alias, model id, annotations) cells per model under a provider.

    Cells are returned unpadded; the caller aligns them into global columns
    so annotations line up across every provider section.
    """
    provider_disabled = provider.disabled
    provider_available = (not provider_disabled) and (not provider.is_api_key_missing())

    def _resolve_selector(value: str) -> str | None:
        if not value:
            return None
        try:
            resolved = config.resolve_model_location_prefer_available(value) or config.resolve_model_location(value)
        except ValueError:
            return None
        if resolved is None:
            return None
        return f"{resolved[0]}@{resolved[1]}"

    def _resolve_model_preference(value: ModelPreference) -> str | None:
        if value is None:
            return None
        if isinstance(value, str):
            return _resolve_selector(value)
        for candidate in value:
            result = _resolve_selector(candidate)
            if result is not None:
                return result
        return None

    default_selector = _resolve_model_preference(config.main_model)

    # Build reverse mapping: model_name -> list of agent roles using it
    model_to_agents: dict[str, list[str]] = {}
    for agent_role, model_name in (config.sub_agent_models or {}).items():
        selector = _resolve_model_preference(model_name)
        if selector is None:
            continue
        if selector not in model_to_agents:
            model_to_agents[selector] = []
        model_to_agents[selector].append(agent_role)

    model_rows: list[tuple[Text, Text, Text]] = []

    for model in provider.model_list:
        params: Text | None = None
        roles: list[str] = []

        if provider_disabled:
            name = Text.assemble(
                (model.model_name, "dim strike"),
                (" (provider disabled)", "dim"),
            )
            model_id = Text()
            model_id.append(model.model_id or "", style="dim")
            status = Text()
            status.append("status: disabled", style="dim")
        elif not provider_available:
            name = Text()
            name.append(model.model_name, style="dim")
            model_id = Text()
            model_id.append(model.model_id or "", style="dim")
            status = Text()
            status.append("status: unavailable", style="dim")
        elif model.disabled:
            name = Text.assemble(
                (model.model_name, "dim strike"),
                (" (disabled)", "dim"),
            )
            model_id = Text()
            model_id.append(model.model_id or "", style="dim")
            status = Text()
            status.append("status: disabled", style="dim")
            params = Text(" · ", style="dim").join(_get_model_params_display(model))
        else:
            # Build role tags for this model
            selector = f"{model.model_name}@{provider.provider_name}"
            if selector == default_selector:
                roles.append("main")
            if selector in model_to_agents:
                roles.extend(role.lower() for role in model_to_agents[selector])
            if roles:
                roles = list(dict.fromkeys(roles))

            name = Text()
            name.append(
                model.model_name,
                style=ThemeKey.CONFIG_STATUS_PRIMARY if roles else ThemeKey.CONFIG_ITEM_NAME,
            )
            model_id = Text()
            model_id.append(model.model_id or "", style=ThemeKey.CONFIG_MODEL_ID)
            params = Text(" · ", style="dim").join(_get_model_params_display(model))
            status = None

        # Annotation column: role bindings first (they answer "which alias do
        # the agent types use"), then model parameters, then status.
        trailing = Text()
        if roles:
            trailing.append_text(Text(" · ", style="dim").join(Text(role, style="yellow") for role in roles))
        if provider_available and (not provider_disabled) and params is not None and params.plain:
            if trailing.plain:
                trailing.append(" · ", style="dim")
            trailing.append_text(params)
        if status is not None:
            if trailing.plain:
                trailing.append(" · ", style="dim")
            trailing.append_text(status)

        model_rows.append((name, model_id, trailing))

    return model_rows


def display_models_and_providers(config: Config, *, show_all: bool = False) -> None:
    """Display providers and models using a compact tree style."""
    themes = get_theme(config.theme)
    console = Console(theme=themes.app_theme)

    # Sort providers: enabled+available first, disabled/unavailable last
    sorted_providers = sorted(
        config.provider_list,
        key=lambda p: (p.disabled, p.is_api_key_missing(), p.provider_name),
    )

    # Filter out disabled/unavailable providers unless show_all is True
    if not show_all:
        sorted_providers = [p for p in sorted_providers if (not p.disabled) and (not p.is_api_key_missing())]

    printed_any_provider = False

    # Cells are config-only, so rows for every provider are known upfront;
    # compute global column widths once so alias, model id, and annotations
    # align across all provider sections (OAuth headers still load async).
    rows_by_provider = {provider.provider_name: _build_model_rows(provider, config) for provider in sorted_providers}
    all_rows = [row for rows in rows_by_provider.values() for row in rows]
    alias_width = max((alias.cell_len for alias, _, _ in all_rows), default=0)
    model_width = max((model_id.cell_len for _, model_id, _ in all_rows), default=0)

    def _print_provider(provider: ProviderConfig, usage_map: dict[LLMClientProtocol, str]) -> None:
        nonlocal printed_any_provider
        if printed_any_provider:
            console.print()
        printed_any_provider = True

        provider_header = _build_provider_header(
            provider,
            oauth_usage_by_protocol=usage_map,
        )
        console.print(provider_header)

        for alias, model_id, trailing in rows_by_provider[provider.provider_name]:
            line = Text("  ")
            line.append_text(_pad_text_right(alias, alias_width))
            if model_id.plain:
                line.append(" → ", style="dim")
                if trailing.plain:
                    line.append_text(_pad_text_right(model_id, model_width))
                else:
                    line.append_text(model_id)
            if trailing.plain:
                line.append("  ")
                line.append_text(trailing)
            console.print(line)

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
        total_groups = len(oauth_provider_groups)
        with ThreadPoolExecutor(max_workers=min(len(oauth_provider_groups), 3)) as executor:
            future_to_protocol = {
                executor.submit(load_oauth_usage_summary, protocols={protocol}, timeout_seconds=3.5): protocol
                for protocol in oauth_provider_groups
            }

            with console.status(
                Text(f"Loading OAuth usage... (0/{total_groups})", style=ThemeKey.STATUS_TEXT),
                spinner="dots",
                spinner_style=ThemeKey.STATUS_SPINNER,
            ) as status:
                for completed_groups, future in enumerate(as_completed(future_to_protocol), start=1):
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
                        # Usage display must never break `klaude agents`.
                        usage_map = {}

                    status.update(
                        Text(f"Loading OAuth usage... ({completed_groups}/{total_groups})", style=ThemeKey.STATUS_TEXT)
                    )

                    for provider in oauth_provider_groups.get(protocol, []):
                        _print_provider(provider, usage_map)
