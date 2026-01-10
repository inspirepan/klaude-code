import asyncio
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, cast

import yaml
from pydantic import BaseModel, Field, ValidationError, model_validator

from klaude_code.auth.env import get_auth_env
from klaude_code.config.builtin_config import (
    SUPPORTED_API_KEYS,
    get_builtin_config,
)
from klaude_code.log import log
from klaude_code.protocol import llm_param
from klaude_code.protocol.sub_agent import iter_sub_agent_profiles

# Pattern to match ${ENV_VAR} syntax
_ENV_VAR_PATTERN = re.compile(r"^\$\{([A-Za-z_][A-Za-z0-9_]*)\}$")


def parse_env_var_syntax(value: str | None) -> tuple[str | None, str | None]:
    """Parse a value that may use ${ENV_VAR} syntax.

    Returns:
        A tuple of (env_var_name, resolved_value).
        - If value uses ${ENV_VAR} syntax: (env_var_name, resolved_value)
          Priority: os.environ > klaude-auth.json env section
        - If value is a plain string: (None, value)
        - If value is None: (None, None)
    """
    if value is None:
        return None, None

    match = _ENV_VAR_PATTERN.match(value)
    if match:
        env_var_name = match.group(1)
        # Priority: real env var > auth.json env section
        resolved = os.environ.get(env_var_name) or get_auth_env(env_var_name)
        return env_var_name, resolved

    return None, value


def resolve_api_key(value: str | None) -> str | None:
    """Resolve an API key value, expanding ${ENV_VAR} syntax if present."""
    _, resolved = parse_env_var_syntax(value)
    return resolved


config_path = Path.home() / ".klaude" / "klaude-config.yaml"
example_config_path = Path.home() / ".klaude" / "klaude-config.example.yaml"


class ModelConfig(llm_param.LLMConfigModelParameter):
    """Model configuration that flattens LLMConfigModelParameter fields."""

    model_name: str


class ProviderConfig(llm_param.LLMConfigProviderParameter):
    """Full provider configuration (used in merged config)."""

    disabled: bool = False
    model_list: list[ModelConfig] = Field(default_factory=lambda: [])

    def get_resolved_api_key(self) -> str | None:
        """Get the resolved API key, expanding ${ENV_VAR} syntax if present."""
        return resolve_api_key(self.api_key)

    def get_api_key_env_var(self) -> str | None:
        """Get the environment variable name if ${ENV_VAR} syntax is used."""
        env_var, _ = parse_env_var_syntax(self.api_key)
        return env_var

    def is_api_key_missing(self) -> bool:
        """Check if the API key is missing (either not set or env var not found).

        For codex protocol, checks OAuth login status instead of API key.
        For bedrock protocol, checks AWS credentials instead of API key.
        """
        from klaude_code.protocol.llm_param import LLMClientProtocol

        if self.protocol == LLMClientProtocol.CODEX_OAUTH:
            # Codex uses OAuth authentication, not API key
            from klaude_code.auth.codex.token_manager import CodexTokenManager

            token_manager = CodexTokenManager()
            state = token_manager.get_state()
            # Consider available if logged in. Token refresh happens on-demand.
            return state is None

        if self.protocol == LLMClientProtocol.CLAUDE_OAUTH:
            # Claude uses OAuth authentication, not API key
            from klaude_code.auth.claude.token_manager import ClaudeTokenManager

            token_manager = ClaudeTokenManager()
            state = token_manager.get_state()
            # Consider available if logged in. Token refresh happens on-demand.
            return state is None

        if self.protocol == LLMClientProtocol.ANTIGRAVITY:
            # Antigravity uses OAuth authentication, not API key
            from klaude_code.auth.antigravity.token_manager import AntigravityTokenManager

            token_manager = AntigravityTokenManager()
            state = token_manager.get_state()
            # Consider available if logged in. Token refresh happens on-demand.
            return state is None

        if self.protocol == LLMClientProtocol.BEDROCK:
            # Bedrock uses AWS credentials, not API key. Region is always required.
            _, resolved_profile = parse_env_var_syntax(self.aws_profile)
            _, resolved_region = parse_env_var_syntax(self.aws_region)

            # When using profile, we still need region to initialize the client.
            if resolved_profile:
                return resolved_region is None

            _, resolved_access_key = parse_env_var_syntax(self.aws_access_key)
            _, resolved_secret_key = parse_env_var_syntax(self.aws_secret_key)
            return resolved_region is None or resolved_access_key is None or resolved_secret_key is None

        return self.get_resolved_api_key() is None


class UserProviderConfig(BaseModel):
    """User provider configuration (allows partial overrides).

    Unlike ProviderConfig, protocol is optional here since user may only want
    to add models to an existing builtin provider.
    """

    provider_name: str
    protocol: llm_param.LLMClientProtocol | None = None
    disabled: bool = False
    base_url: str | None = None
    api_key: str | None = None
    is_azure: bool = False
    azure_api_version: str | None = None
    model_list: list[ModelConfig] = Field(default_factory=lambda: [])


class ModelEntry(llm_param.LLMConfigModelParameter):
    """Model entry with provider info, flattens LLMConfigModelParameter fields."""

    model_name: str
    provider: str

    @property
    def selector(self) -> str:
        """Return a provider-qualified model selector.

        This selector can be persisted in user config (e.g. ``sonnet@openrouter``)
        and later resolved via :meth:`Config.get_model_config`.
        """

        return f"{self.model_name}@{self.provider}"


class UserConfig(BaseModel):
    """User configuration (what gets saved to disk)."""

    main_model: str | None = None
    compact_model: str | None = None
    sub_agent_models: dict[str, str] = Field(default_factory=dict)
    theme: str | None = None
    provider_list: list[UserProviderConfig] = Field(default_factory=lambda: [])

    @model_validator(mode="before")
    @classmethod
    def _normalize_sub_agent_models(cls, data: dict[str, Any]) -> dict[str, Any]:
        raw_val: Any = data.get("sub_agent_models") or {}
        raw_models: dict[str, Any] = cast(dict[str, Any], raw_val) if isinstance(raw_val, dict) else {}
        normalized: dict[str, str] = {}
        key_map = {p.name.lower(): p.name for p in iter_sub_agent_profiles()}
        for key, value in dict(raw_models).items():
            canonical = key_map.get(str(key).lower(), str(key))
            normalized[canonical] = str(value)
        data["sub_agent_models"] = normalized
        return data


class Config(BaseModel):
    """Merged configuration (builtin + user) for runtime use."""

    main_model: str | None = None
    compact_model: str | None = None
    sub_agent_models: dict[str, str] = Field(default_factory=dict)
    theme: str | None = None
    provider_list: list[ProviderConfig] = Field(default_factory=lambda: [])

    # Internal: reference to original user config for saving
    _user_config: UserConfig | None = None

    @model_validator(mode="before")
    @classmethod
    def _normalize_sub_agent_models(cls, data: dict[str, Any]) -> dict[str, Any]:
        raw_val: Any = data.get("sub_agent_models") or {}
        raw_models: dict[str, Any] = cast(dict[str, Any], raw_val) if isinstance(raw_val, dict) else {}
        normalized: dict[str, str] = {}
        key_map = {p.name.lower(): p.name for p in iter_sub_agent_profiles()}
        for key, value in dict(raw_models).items():
            canonical = key_map.get(str(key).lower(), str(key))
            normalized[canonical] = str(value)
        data["sub_agent_models"] = normalized
        return data

    def set_user_config(self, user_config: UserConfig | None) -> None:
        """Set the user config reference for saving."""
        object.__setattr__(self, "_user_config", user_config)

    @classmethod
    def _split_model_selector(cls, model_selector: str) -> tuple[str, str | None]:
        """Split a model selector into (model_name, provider_name).

        Supported forms:
        - ``sonnet``: unqualified; caller should pick the first matching provider.
        - ``sonnet@openrouter``: provider-qualified.

        Note: the provider segment is normalized for backwards compatibility.
        """

        trimmed = model_selector.strip()
        if "@" not in trimmed:
            return trimmed, None

        base, provider = trimmed.rsplit("@", 1)
        base = base.strip()
        provider = provider.strip()
        if not base or not provider:
            raise ValueError(f"Invalid model selector: {model_selector!r}")
        return base, provider

    def has_model_config_name(self, model_selector: str) -> bool:
        """Return True if the selector points to a configured model.

        This check is configuration-only: it does not require a valid API key or
        OAuth login.
        """

        model_name, provider_name = self._split_model_selector(model_selector)
        if provider_name is not None:
            for provider in self.provider_list:
                if provider.provider_name.casefold() != provider_name.casefold():
                    continue
                return any(m.model_name == model_name for m in provider.model_list)
            return False

        return any(any(m.model_name == model_name for m in provider.model_list) for provider in self.provider_list)

    def resolve_model_location(self, model_selector: str) -> tuple[str, str] | None:
        """Resolve a selector to (model_name, provider_name), without auth checks.

        - If the selector is provider-qualified, returns that provider.
        - If unqualified, returns the first provider that defines the model.
        """

        model_name, provider_name = self._split_model_selector(model_selector)
        if provider_name is not None:
            for provider in self.provider_list:
                if provider.provider_name.casefold() != provider_name.casefold():
                    continue
                if any(m.model_name == model_name for m in provider.model_list):
                    return model_name, provider.provider_name
            return None

        for provider in self.provider_list:
            if any(m.model_name == model_name for m in provider.model_list):
                return model_name, provider.provider_name
        return None

    def resolve_model_location_prefer_available(self, model_selector: str) -> tuple[str, str] | None:
        """Resolve a selector to (model_name, provider_name), preferring usable providers.

        This uses the same availability logic as :meth:`get_model_config` (API-key
        presence for non-OAuth protocols).
        """

        requested_model, requested_provider = self._split_model_selector(model_selector)

        for provider in self.provider_list:
            if requested_provider is not None and provider.provider_name.casefold() != requested_provider.casefold():
                continue

            if provider.disabled:
                continue

            api_key = provider.get_resolved_api_key()
            if (
                provider.protocol
                not in {
                    llm_param.LLMClientProtocol.CODEX_OAUTH,
                    llm_param.LLMClientProtocol.CLAUDE_OAUTH,
                    llm_param.LLMClientProtocol.ANTIGRAVITY,
                    llm_param.LLMClientProtocol.BEDROCK,
                }
                and not api_key
            ):
                continue

            for model in provider.model_list:
                if model.model_name != requested_model:
                    continue
                if model.disabled:
                    continue
                return requested_model, provider.provider_name

        return None

    def get_model_config(self, model_name: str) -> llm_param.LLMConfigParameter:
        requested_model, requested_provider = self._split_model_selector(model_name)

        for provider in self.provider_list:
            if requested_provider is not None and provider.provider_name.casefold() != requested_provider.casefold():
                continue

            if provider.disabled:
                if requested_provider is not None:
                    raise ValueError(f"Provider '{provider.provider_name}' is disabled for: {model_name}")
                continue

            # Resolve ${ENV_VAR} syntax for api_key
            api_key = provider.get_resolved_api_key()

            # Some protocols do not use API keys for authentication.
            if (
                provider.protocol
                not in {
                    llm_param.LLMClientProtocol.CODEX_OAUTH,
                    llm_param.LLMClientProtocol.CLAUDE_OAUTH,
                    llm_param.LLMClientProtocol.ANTIGRAVITY,
                    llm_param.LLMClientProtocol.BEDROCK,
                }
                and not api_key
            ):
                # When provider is explicitly requested, fail fast with a clearer error.
                if requested_provider is not None:
                    raise ValueError(
                        f"Provider '{provider.provider_name}' is not available (missing API key) for: {model_name}"
                    )
                continue

            for model in provider.model_list:
                if model.model_name != requested_model:
                    continue

                if model.disabled:
                    if requested_provider is not None:
                        raise ValueError(
                            f"Model '{requested_model}' is disabled in provider '{provider.provider_name}' for: {model_name}"
                        )
                    break

                provider_dump = provider.model_dump(exclude={"model_list", "disabled"})
                provider_dump["api_key"] = api_key
                return llm_param.LLMConfigParameter(
                    **provider_dump,
                    **model.model_dump(exclude={"model_name"}),
                )

        raise ValueError(f"Unknown model: {model_name}")

    def iter_model_entries(self, only_available: bool = False, include_disabled: bool = True) -> list[ModelEntry]:
        """Return all model entries with their provider names.

        Args:
            only_available: If True, only return models from providers with valid API keys.
            include_disabled: If False, exclude models/providers with disabled=True.
        """
        return [
            ModelEntry(
                model_name=model.model_name,
                provider=provider.provider_name,
                **model.model_dump(exclude={"model_name"}),
            )
            for provider in self.provider_list
            if include_disabled or not provider.disabled
            if not only_available or (not provider.disabled and not provider.is_api_key_missing())
            for model in provider.model_list
            if include_disabled or not model.disabled
        ]

    def has_available_image_model(self) -> bool:
        """Check if any image generation model is available."""
        for entry in self.iter_model_entries(only_available=True, include_disabled=False):
            if entry.modalities and "image" in entry.modalities:
                return True
        return False

    def get_first_available_image_model(self) -> str | None:
        """Get the first available image generation model, or None."""
        for entry in self.iter_model_entries(only_available=True, include_disabled=False):
            if entry.modalities and "image" in entry.modalities:
                return entry.model_name
        return None

    async def save(self) -> None:
        """Save user config to file (excludes builtin providers).

        Only saves user-specific settings like main_model and custom providers.
        Builtin providers are never written to the user config file.
        """
        # Get user config, creating one if needed
        user_config = self._user_config
        if user_config is None:
            user_config = UserConfig()

        # Sync user-modifiable fields from merged config to user config
        user_config.main_model = self.main_model
        user_config.compact_model = self.compact_model
        user_config.sub_agent_models = self.sub_agent_models
        user_config.theme = self.theme
        # Note: provider_list is NOT synced - user providers are already in user_config

        # Keep the saved file compact (exclude defaults), but preserve explicit
        # overrides inside provider_list (e.g. `disabled: false` to re-enable a
        # builtin provider that is disabled by default).
        config_dict = user_config.model_dump(
            mode="json",
            exclude_none=True,
            exclude_defaults=True,
            exclude={"provider_list"},
        )

        provider_list = [
            p.model_dump(mode="json", exclude_none=True, exclude_unset=True) for p in (user_config.provider_list or [])
        ]
        if provider_list:
            config_dict["provider_list"] = provider_list

        def _save_config() -> None:
            config_path.parent.mkdir(parents=True, exist_ok=True)
            yaml_content = yaml.dump(config_dict, default_flow_style=False, sort_keys=False)
            _ = config_path.write_text(str(yaml_content or ""))

        await asyncio.to_thread(_save_config)


def get_example_config() -> UserConfig:
    """Generate example config for user reference (will be commented out)."""
    return UserConfig(
        main_model="opus",
        compact_model="gemini-flash",
        sub_agent_models={"explore": "haiku", "webagent": "sonnet", "task": "sonnet"},
        provider_list=[
            UserProviderConfig(
                provider_name="my-provider",
                protocol=llm_param.LLMClientProtocol.OPENAI,
                api_key="${MY_API_KEY}",
                base_url="https://api.example.com/v1",
                model_list=[
                    ModelConfig(
                        model_name="my-model",
                        model_id="model-id-from-provider",
                        max_tokens=16000,
                        context_limit=200000,
                        cost=llm_param.Cost(
                            input=1,
                            output=10,
                            cache_read=0.1,
                        ),
                    ),
                ],
            ),
        ],
    )


def _get_builtin_config() -> Config:
    """Load built-in provider configurations."""
    return get_builtin_config()


def _merge_model(builtin: ModelConfig, user: ModelConfig) -> ModelConfig:
    """Merge user model config with builtin model config.

    Strategy: user values take precedence if explicitly set (not unset).
    This allows users to override specific fields (e.g., disabled=true/false)
    without losing other builtin settings (e.g., model_id, max_tokens).
    """
    merged_data = builtin.model_dump()
    user_data = user.model_dump(exclude_unset=True, exclude={"model_name"})
    for key, value in user_data.items():
        if value is not None:
            merged_data[key] = value
    return ModelConfig.model_validate(merged_data)


def _merge_provider(builtin: ProviderConfig, user: UserProviderConfig) -> ProviderConfig:
    """Merge user provider config with builtin provider config.

    Strategy:
    - model_list: merge by model_name, user model fields override builtin fields
    - Other fields (api_key, base_url, etc.): user config takes precedence if set
    """
    # Merge model_list: builtin first, then user overrides/appends
    merged_models: dict[str, ModelConfig] = {}
    for m in builtin.model_list:
        merged_models[m.model_name] = m
    for m in user.model_list:
        if m.model_name in merged_models:
            # Merge with builtin model
            merged_models[m.model_name] = _merge_model(merged_models[m.model_name], m)
        else:
            # New model from user
            merged_models[m.model_name] = m

    # For other fields, use user values if explicitly set, otherwise use builtin.
    merged_data = builtin.model_dump()
    user_data = user.model_dump(exclude_unset=True, exclude={"model_list"})

    # Update with user's explicit settings
    for key, value in user_data.items():
        if value is not None:
            merged_data[key] = value

    merged_data["model_list"] = [m.model_dump() for m in merged_models.values()]
    return ProviderConfig.model_validate(merged_data)


def _merge_configs(user_config: UserConfig | None, builtin_config: Config) -> Config:
    """Merge user config with builtin config.

    Strategy:
    - provider_list: merge by provider_name
      - Same name: merge model_list (user models override/append), other fields user takes precedence
      - New name: add to list
    - main_model: user config takes precedence
    - sub_agent_models: merge, user takes precedence
    - theme: user config takes precedence

    The returned Config keeps a reference to user_config for saving.
    """
    if user_config is None:
        # No user config - return builtin with empty user config reference
        merged = builtin_config.model_copy()
        merged.set_user_config(None)
        return merged

    # Build lookup for builtin providers
    builtin_providers: dict[str, ProviderConfig] = {p.provider_name: p for p in builtin_config.provider_list}

    # Merge provider_list
    merged_providers: dict[str, ProviderConfig] = dict(builtin_providers)
    for user_provider in user_config.provider_list:
        if user_provider.provider_name in builtin_providers:
            # Merge with builtin provider
            merged_providers[user_provider.provider_name] = _merge_provider(
                builtin_providers[user_provider.provider_name], user_provider
            )
        else:
            # New provider from user - must have protocol
            if user_provider.protocol is None:
                raise ValueError(
                    f"Provider '{user_provider.provider_name}' requires 'protocol' field (not a builtin provider)"
                )
            merged_providers[user_provider.provider_name] = ProviderConfig.model_validate(user_provider.model_dump())

    # Merge sub_agent_models
    merged_sub_agent_models = {**builtin_config.sub_agent_models, **user_config.sub_agent_models}

    # Re-validate providers to ensure compatibility (tests may monkeypatch the class)
    revalidated_providers = [ProviderConfig.model_validate(p.model_dump()) for p in merged_providers.values()]
    merged = Config(
        main_model=user_config.main_model or builtin_config.main_model,
        compact_model=user_config.compact_model or builtin_config.compact_model,
        sub_agent_models=merged_sub_agent_models,
        theme=user_config.theme or builtin_config.theme,
        provider_list=revalidated_providers,
    )
    # Keep reference to user config for saving
    merged.set_user_config(user_config)
    return merged


def _load_user_config() -> UserConfig | None:
    """Load user config from disk. Returns None if file doesn't exist or is empty."""
    if not config_path.exists():
        return None

    config_yaml = config_path.read_text()
    config_dict = yaml.safe_load(config_yaml)

    if config_dict is None:
        return None

    try:
        return UserConfig.model_validate(config_dict)
    except ValidationError as e:
        log(f"Invalid config file: {config_path}", style="red")
        log(str(e), style="red")
        raise ValueError(f"Invalid config file: {config_path}") from e


def create_example_config() -> bool:
    """Create example config file if it doesn't exist.

    Returns:
        True if file was created, False if it already exists.
    """
    if example_config_path.exists():
        return False

    example_config = get_example_config()
    example_config_path.parent.mkdir(parents=True, exist_ok=True)
    config_dict = example_config.model_dump(mode="json", exclude_none=True)

    yaml_str = yaml.dump(config_dict, default_flow_style=False, sort_keys=False) or ""
    header = "# Example configuration for klaude-code\n"
    header += "# Copy this file to klaude-config.yaml and modify as needed.\n"
    header += "# Run `klaude list` to see available models.\n"
    header += "# Tip: you can pick a provider explicitly with `model@provider` (e.g. `sonnet@openrouter`).\n"
    header += (
        "# If you omit `@provider` (e.g. `sonnet`), klaude picks the first configured provider with credentials.\n"
    )
    header += "#\n"
    header += "# Built-in providers (anthropic, openai, openrouter, deepseek) are available automatically.\n"
    header += "# Just set the corresponding API key environment variable to use them.\n\n"
    _ = example_config_path.write_text(header + yaml_str)
    return True


def _load_config_uncached() -> Config:
    """Load and merge builtin + user config. Always returns a valid Config."""
    builtin_config = _get_builtin_config()

    user_config = _load_user_config()

    return _merge_configs(user_config, builtin_config)


@lru_cache(maxsize=1)
def _load_config_cached() -> Config:
    return _load_config_uncached()


def load_config() -> Config:
    """Load config from disk (builtin + user merged).

    Always returns a valid Config. Use
    ``config.iter_model_entries(only_available=True, include_disabled=False)``
    to check if any models are actually usable.
    """
    try:
        return _load_config_cached()
    except ValueError:
        _load_config_cached.cache_clear()
        raise


def print_no_available_models_hint() -> None:
    """Print helpful message when no models are available due to missing API keys."""
    log("No available models. Configure an API key using one of these methods:", style="yellow")
    log("")
    log("Option 1: Use klaude auth login", style="bold")
    # Use first word of name for brevity
    names = [k.name.split()[0].lower() for k in SUPPORTED_API_KEYS]
    log(f"  klaude auth login <provider>  (providers: {', '.join(names)})", style="dim")
    log("")
    log("Option 2: Set environment variables", style="bold")
    max_len = max(len(k.env_var) for k in SUPPORTED_API_KEYS)
    for key_info in SUPPORTED_API_KEYS:
        current_value = os.environ.get(key_info.env_var) or get_auth_env(key_info.env_var)
        if current_value:
            log(f"  {key_info.env_var:<{max_len}}  (set)", style="green")
        else:
            log(f"  {key_info.env_var:<{max_len}}  {key_info.description}", style="dim")
    log("")
    log(f"Or add custom providers in: {config_path}", style="dim")


# Expose cache control for tests and callers that need to invalidate the cache.
load_config.cache_clear = _load_config_cached.cache_clear  # type: ignore[attr-defined]
