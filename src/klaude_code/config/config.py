import asyncio
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, cast

import yaml
from pydantic import BaseModel, Field, ValidationError, model_validator

from klaude_code.config.builtin_config import SUPPORTED_API_KEY_ENVS, get_builtin_provider_configs
from klaude_code.protocol import llm_param
from klaude_code.protocol.sub_agent import iter_sub_agent_profiles
from klaude_code.trace import log

# Pattern to match ${ENV_VAR} syntax
_ENV_VAR_PATTERN = re.compile(r"^\$\{([A-Za-z_][A-Za-z0-9_]*)\}$")


def parse_env_var_syntax(value: str | None) -> tuple[str | None, str | None]:
    """Parse a value that may use ${ENV_VAR} syntax.

    Returns:
        A tuple of (env_var_name, resolved_value).
        - If value uses ${ENV_VAR} syntax: (env_var_name, os.environ.get(env_var_name))
        - If value is a plain string: (None, value)
        - If value is None: (None, None)
    """
    if value is None:
        return None, None

    match = _ENV_VAR_PATTERN.match(value)
    if match:
        env_var_name = match.group(1)
        return env_var_name, os.environ.get(env_var_name)

    return None, value


def is_env_var_syntax(value: str | None) -> bool:
    """Check if a value uses ${ENV_VAR} syntax."""
    if value is None:
        return False
    return _ENV_VAR_PATTERN.match(value) is not None


def resolve_api_key(value: str | None) -> str | None:
    """Resolve an API key value, expanding ${ENV_VAR} syntax if present."""
    _, resolved = parse_env_var_syntax(value)
    return resolved


config_path = Path.home() / ".klaude" / "klaude-config.yaml"
example_config_path = Path.home() / ".klaude" / "klaude-config.example.yaml"


class ModelConfig(BaseModel):
    model_name: str
    model_params: llm_param.LLMConfigModelParameter


class ProviderConfig(llm_param.LLMConfigProviderParameter):
    """Full provider configuration (used in merged config)."""

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
        """
        from klaude_code.protocol.llm_param import LLMClientProtocol

        if self.protocol == LLMClientProtocol.CODEX:
            # Codex uses OAuth authentication, not API key
            from klaude_code.auth.codex.token_manager import CodexTokenManager

            token_manager = CodexTokenManager()
            state = token_manager.get_state()
            # Consider available if logged in and token not expired
            return state is None or state.is_expired()

        return self.get_resolved_api_key() is None


class UserProviderConfig(BaseModel):
    """User provider configuration (allows partial overrides).

    Unlike ProviderConfig, protocol is optional here since user may only want
    to add models to an existing builtin provider.
    """

    provider_name: str
    protocol: llm_param.LLMClientProtocol | None = None
    base_url: str | None = None
    api_key: str | None = None
    is_azure: bool = False
    azure_api_version: str | None = None
    model_list: list[ModelConfig] = Field(default_factory=lambda: [])


class ModelEntry(BaseModel):
    model_name: str
    provider: str
    model_params: llm_param.LLMConfigModelParameter


class UserConfig(BaseModel):
    """User configuration (what gets saved to disk)."""

    main_model: str | None = None
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

    def get_model_config(self, model_name: str) -> llm_param.LLMConfigParameter:
        for provider in self.provider_list:
            # Resolve ${ENV_VAR} syntax for api_key
            api_key = provider.get_resolved_api_key()
            if not api_key:
                continue
            for model in provider.model_list:
                if model.model_name == model_name:
                    provider_dump = provider.model_dump(exclude={"model_list"})
                    provider_dump["api_key"] = api_key
                    return llm_param.LLMConfigParameter(
                        **provider_dump,
                        **model.model_params.model_dump(),
                    )

        raise ValueError(f"Unknown model: {model_name}")

    def iter_model_entries(self, only_available: bool = False) -> list[ModelEntry]:
        """Return all model entries with their provider names.

        Args:
            only_available: If True, only return models from providers with valid API keys.
        """
        return [
            ModelEntry(
                model_name=model.model_name,
                provider=provider.provider_name,
                model_params=model.model_params,
            )
            for provider in self.provider_list
            if not only_available or not provider.is_api_key_missing()
            for model in provider.model_list
        ]

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
        user_config.sub_agent_models = self.sub_agent_models
        user_config.theme = self.theme
        # Note: provider_list is NOT synced - user providers are already in user_config

        config_dict = user_config.model_dump(mode="json", exclude_none=True, exclude_defaults=True)

        def _save_config() -> None:
            config_path.parent.mkdir(parents=True, exist_ok=True)
            yaml_content = yaml.dump(config_dict, default_flow_style=False, sort_keys=False)
            _ = config_path.write_text(str(yaml_content or ""))

        await asyncio.to_thread(_save_config)


def get_example_config() -> UserConfig:
    """Generate example config for user reference (will be commented out)."""
    return UserConfig(
        main_model="opus",
        sub_agent_models={"explore": "haiku", "oracle": "gpt-5.2", "webagent": "sonnet", "task": "sonnet"},
        provider_list=[
            UserProviderConfig(
                provider_name="my-provider",
                protocol=llm_param.LLMClientProtocol.OPENAI,
                api_key="${MY_API_KEY}",
                base_url="https://api.example.com/v1",
                model_list=[
                    ModelConfig(
                        model_name="my-model",
                        model_params=llm_param.LLMConfigModelParameter(
                            model="model-id-from-provider",
                            max_tokens=16000,
                            context_limit=200000,
                        ),
                    ),
                ],
            ),
        ],
    )


def _get_builtin_config() -> Config:
    """Load built-in provider configurations."""
    # Re-validate to ensure compatibility with current ProviderConfig class
    # (needed for tests that may monkeypatch the class)
    providers = [ProviderConfig.model_validate(p.model_dump()) for p in get_builtin_provider_configs()]
    return Config(provider_list=providers)


def _merge_provider(builtin: ProviderConfig, user: UserProviderConfig) -> ProviderConfig:
    """Merge user provider config with builtin provider config.

    Strategy:
    - model_list: merge by model_name, user models override builtin models with same name
    - Other fields (api_key, base_url, etc.): user config takes precedence if set
    """
    # Merge model_list: builtin first, then user overrides/appends
    merged_models: dict[str, ModelConfig] = {}
    for m in builtin.model_list:
        merged_models[m.model_name] = m
    for m in user.model_list:
        merged_models[m.model_name] = m

    # For other fields, use user values if explicitly set, otherwise use builtin
    # We check if user explicitly provided a value by comparing to defaults
    merged_data = builtin.model_dump()
    user_data = user.model_dump(exclude_defaults=True, exclude={"model_list"})

    # Update with user's explicit settings
    for key, value in user_data.items():
        if value is not None:
            merged_data[key] = value

    merged_data["model_list"] = list(merged_models.values())
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

    merged = Config(
        main_model=user_config.main_model or builtin_config.main_model,
        sub_agent_models=merged_sub_agent_models,
        theme=user_config.theme or builtin_config.theme,
        provider_list=list(merged_providers.values()),
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
        log(f"Invalid config file: {config_path}", style="red bold")
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

    Always returns a valid Config. Use config.iter_model_entries(only_available=True)
    to check if any models are actually usable.
    """
    try:
        return _load_config_cached()
    except ValueError:
        _load_config_cached.cache_clear()
        raise


def print_no_available_models_hint() -> None:
    """Print helpful message when no models are available due to missing API keys."""
    log("No available models. Please set one of the following environment variables:", style="yellow")
    log("")
    for env_var in SUPPORTED_API_KEY_ENVS:
        current_value = os.environ.get(env_var)
        if current_value:
            log(f"  {env_var} = (set)", style="green")
        else:
            log(f"  export {env_var}=<your-api-key>", style="dim")
    log("")
    log(f"Or add custom providers in: {config_path}", style="dim")
    log(f"See example config: {example_config_path}", style="dim")


# Expose cache control for tests and callers that need to invalidate the cache.
load_config.cache_clear = _load_config_cached.cache_clear  # type: ignore[attr-defined]
