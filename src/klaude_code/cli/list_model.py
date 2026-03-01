from concurrent.futures import ThreadPoolExecutor, as_completed

from rich.console import Console
from rich.text import Text

from klaude_code.cli.oauth_usage import (
    format_oauth_usage_summary,
    load_oauth_usage_summary,
    resolve_oauth_usage_protocol,
)
from klaude_code.config import Config
from klaude_code.config.config import ModelConfig, ProviderConfig, parse_env_var_syntax
from klaude_code.protocol.llm_param import LLMClientProtocol
from klaude_code.tui.components.rich.theme import ThemeKey, get_theme
from klaude_code.ui.common import format_model_params


def mask_api_key(api_key: str | None) -> str:
    """Mask API key to show only first 6 and last 6 characters with *** in between"""
    if not api_key:
        return ""

    if len(api_key) <= 12:
        return api_key

    return f"{api_key[:6]}…{api_key[-6:]}"


def _format_secret_value_display(value: str | None, *, fallback_name: str) -> Text:
    """Format `${ENV}` or raw secret as `NAME=masked`.

    For `${A|B}` syntax, keep the expression as-is to show fallback order.
    """
    env_var, resolved = parse_env_var_syntax(value)

    if env_var:
        if resolved:
            return Text.assemble(
                (f"{env_var}=", "dim"),
                (mask_api_key(resolved), ThemeKey.CONFIG_PARAM_VALUE),
            )
        return Text.assemble((f"{env_var}=", "dim"), ("(not set)", ThemeKey.CONFIG_STATUS_ERROR))
    if value:
        return Text.assemble((f"{fallback_name}=", "dim"), (mask_api_key(value), ThemeKey.CONFIG_PARAM_VALUE))
    return Text("")


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


def _build_model_lines(
    provider: ProviderConfig,
    config: Config,
) -> list[Text]:
    """Build one formatted output line per model under a provider."""
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

    model_rows: list[tuple[Text, Text, Text | None, Text | None]] = []

    for model in provider.model_list:
        params: Text | None = None

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
            roles: list[str] = []
            selector = f"{model.model_name}@{provider.provider_name}"
            if selector == default_selector:
                roles.append("main")
            if selector in model_to_agents:
                roles.extend(role.lower() for role in model_to_agents[selector])
            if roles:
                roles = list(dict.fromkeys(roles))

            name = Text()
            if roles:
                name.append(model.model_name, style=ThemeKey.CONFIG_STATUS_PRIMARY)
                name.append(f" ({', '.join(roles)})", style="dim")
            else:
                name.append(model.model_name, style=ThemeKey.CONFIG_ITEM_NAME)
            model_id = Text()
            model_id.append(model.model_id or "", style=ThemeKey.CONFIG_MODEL_ID)
            params = Text(" · ", style="dim").join(_get_model_params_display(model))
            status = None

        model_rows.append((name, model_id, status, params))

    name_width = max((name.cell_len for name, _, _, _ in model_rows), default=0)

    lines: list[Text] = []
    for name, model_id, status, params in model_rows:
        line = _pad_text_right(name, name_width)

        if model_id.plain:
            line.append(" → ", style="dim")
            line.append_text(model_id)

        if provider_available and (not provider_disabled) and params is not None and params.plain:
            line.append(" · ", style="dim")
            line.append_text(params)

        if status is not None:
            line.append(" · ", style="dim")
            line.append_text(status)

        lines.append(line)

    return lines


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

        model_lines = _build_model_lines(provider, config)
        for index, line in enumerate(model_lines):
            branch = "╰── " if index == len(model_lines) - 1 else "├── "
            prefix = Text.assemble(("  ", ""), (branch, ThemeKey.LINES))
            prefix.append_text(line)
            console.print(prefix)

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
                        # Usage display must never break `klaude list`.
                        usage_map = {}

                    status.update(
                        Text(f"Loading OAuth usage... ({completed_groups}/{total_groups})", style=ThemeKey.STATUS_TEXT)
                    )

                    for provider in oauth_provider_groups.get(protocol, []):
                        _print_provider(provider, usage_map)
