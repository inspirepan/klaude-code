"""Config loading, saving, and example generation."""

from __future__ import annotations

import os
from functools import lru_cache

import yaml
from pydantic import ValidationError

import klaude_code.config.config as _schema
from klaude_code.auth.env import get_auth_env
from klaude_code.config.builtin_config import SUPPORTED_API_KEYS, get_builtin_config
from klaude_code.config.merge import merge_configs
from klaude_code.log import log
from klaude_code.protocol import llm_param


def get_example_config() -> _schema.UserConfig:
    """Generate example config for user reference (will be commented out)."""
    return _schema.UserConfig(
        main_model="opus",
        fast_model=["haiku", "gemini-flash", "gpt-5-nano"],
        compact_model=["gemini-flash", "haiku"],
        sub_agent_models={"general-purpose": "sonnet", "finder": "haiku"},
        provider_list=[
            _schema.UserProviderConfig(
                provider_name="my-provider",
                protocol=llm_param.LLMClientProtocol.OPENAI,
                api_key="${MY_API_KEY}",
                base_url="https://api.example.com/v1",
                model_list=[
                    _schema.ModelConfig(
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


def create_example_config() -> bool:
    """Create example config file if it doesn't exist.

    Returns:
        True if file was created, False if it already exists.
    """
    if _schema.example_config_path.exists():
        return False

    example_config = get_example_config()
    _schema.example_config_path.parent.mkdir(parents=True, exist_ok=True)
    config_dict = example_config.model_dump(mode="json", exclude_none=True)

    yaml_str = yaml.dump(config_dict, default_flow_style=False, sort_keys=False) or ""
    header = (
        "# Example configuration for klaude-code\n"
        "# Copy this file to klaude-config.yaml and modify as needed.\n"
        "# Run `klaude list` to see available models.\n"
        "# Tip: you can pick a provider explicitly with `model@provider` (e.g. `sonnet@openrouter`).\n"
        "# If you omit `@provider` (e.g. `sonnet`), klaude picks the first configured provider with credentials.\n"
        "#\n"
        "# Built-in providers (anthropic, openai, openrouter, deepseek) are available automatically.\n"
        "# Just set the corresponding API key environment variable to use them.\n\n"
    )
    _schema.example_config_path.write_text(header + yaml_str)
    return True


def _load_user_config() -> _schema.UserConfig | None:
    """Load user config from disk. Returns None if file doesn't exist or is empty."""
    if not _schema.config_path.exists():
        return None

    config_yaml = _schema.config_path.read_text()
    config_dict = yaml.safe_load(config_yaml)

    if config_dict is None:
        return None

    try:
        return _schema.UserConfig.model_validate(config_dict)
    except ValidationError as e:
        log(f"Invalid config file: {_schema.config_path}")
        log(str(e))
        raise ValueError(f"Invalid config file: {_schema.config_path}") from e


def _load_config_uncached() -> _schema.Config:
    """Load and merge builtin + user config. Always returns a valid Config."""
    builtin_config = get_builtin_config()
    user_config = _load_user_config()
    return merge_configs(user_config, builtin_config)


@lru_cache(maxsize=1)
def _load_config_cached() -> _schema.Config:
    return _load_config_uncached()


class _LoadConfig:
    """Callable wrapper for load_config that exposes cache_clear."""

    def __call__(self) -> _schema.Config:
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

    def cache_clear(self) -> None:
        """Clear the config cache, forcing a fresh load on next call."""
        _load_config_cached.cache_clear()


load_config = _LoadConfig()


def print_no_available_models_hint() -> None:
    """Print helpful message when no models are available due to missing API keys."""
    log("No available models. Configure an API key using one of these methods:")
    log("")
    log("Option 1: Use klaude auth login")
    # Use first word of name for brevity
    names = [k.name.split()[0].lower() for k in SUPPORTED_API_KEYS]
    log(f"  klaude auth login <provider>  (providers: {', '.join(names)})")
    log("")
    log("Option 2: Set environment variables")
    max_len = max(len(k.env_var) for k in SUPPORTED_API_KEYS)
    for key_info in SUPPORTED_API_KEYS:
        current_value = os.environ.get(key_info.env_var) or get_auth_env(key_info.env_var)
        if current_value:
            log(f"  {key_info.env_var:<{max_len}}  (set)")
        else:
            log(f"  {key_info.env_var:<{max_len}}  {key_info.description}")
    log("")
    log(f"Or add custom providers in: {_schema.config_path}")
