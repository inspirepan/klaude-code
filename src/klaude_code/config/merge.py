"""Config merge logic: combine builtin and user configurations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from klaude_code.config.config import (
    Config,
    ModelConfig,
    ProviderConfig,
    UserProviderConfig,
    normalize_provider_name,
)

if TYPE_CHECKING:
    from klaude_code.config.config import UserConfig


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


def merge_configs(user_config: UserConfig | None, builtin_config: Config) -> Config:
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
        # No user config - still re-validate so local ProviderConfig behavior is applied.
        revalidated_providers = [ProviderConfig.model_validate(p.model_dump()) for p in builtin_config.provider_list]
        merged = Config(
            main_model=builtin_config.main_model,
            fast_model=builtin_config.fast_model,
            compact_model=builtin_config.compact_model,
            sub_agent_models=dict(builtin_config.sub_agent_models),
            theme=builtin_config.theme,
            provider_list=revalidated_providers,
        )
        merged.set_user_config(None)
        return merged

    # Build lookup for builtin providers
    builtin_providers: dict[str, ProviderConfig] = {
        normalize_provider_name(p.provider_name): p for p in builtin_config.provider_list
    }

    # Merge provider_list: user providers come first (higher priority in model resolution),
    # followed by builtin-only providers.
    merged_providers: dict[str, ProviderConfig] = {}
    for user_provider in user_config.provider_list:
        provider_name = normalize_provider_name(user_provider.provider_name)
        if provider_name in builtin_providers:
            # Merge with builtin provider; place merged entry first (user priority)
            merged_providers[provider_name] = _merge_provider(builtin_providers[provider_name], user_provider)
        else:
            # New provider from user - must have protocol
            if user_provider.protocol is None:
                raise ValueError(f"Provider '{provider_name}' requires 'protocol' field (not a builtin provider)")
            merged_providers[provider_name] = ProviderConfig.model_validate(user_provider.model_dump())
    # Append builtin providers not referenced by user config
    for name, provider in builtin_providers.items():
        if name not in merged_providers:
            merged_providers[name] = provider

    # Merge sub_agent_models
    merged_sub_agent_models = {**builtin_config.sub_agent_models, **user_config.sub_agent_models}

    # Re-validate providers to ensure compatibility (tests may monkeypatch the class)
    revalidated_providers = [ProviderConfig.model_validate(p.model_dump()) for p in merged_providers.values()]
    merged = Config(
        main_model=user_config.main_model or builtin_config.main_model,
        fast_model=user_config.fast_model or builtin_config.fast_model,
        compact_model=user_config.compact_model or builtin_config.compact_model,
        sub_agent_models=merged_sub_agent_models,
        theme=user_config.theme or builtin_config.theme,
        auto_upgrade=(user_config.auto_upgrade if user_config.auto_upgrade is not None else builtin_config.auto_upgrade),
        provider_list=revalidated_providers,
    )
    # Keep reference to user config for saving
    merged.set_user_config(user_config)
    return merged
