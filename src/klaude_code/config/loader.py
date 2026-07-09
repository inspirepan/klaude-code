"""Config loading, saving, and example generation."""

from __future__ import annotations

import difflib
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

import klaude_code.config.config as _schema
from klaude_code.auth.env import get_auth_env
from klaude_code.config.builtin_config import SUPPORTED_API_KEYS, get_builtin_config
from klaude_code.config.merge import merge_configs
from klaude_code.log import log
from klaude_code.protocol import llm_param


class ConfigValidationError(ValueError):
    """Raised when the user config file fails schema or YAML validation."""

    def __init__(self, path: Path, message: str) -> None:
        self.path = path
        super().__init__(message)


def _format_error_loc(loc: tuple[Any, ...]) -> str:
    """Format a pydantic error location as ``provider_list[2].provider_name``."""
    parts: list[str] = []
    for item in loc:
        if isinstance(item, int):
            if parts:
                parts[-1] = f"{parts[-1]}[{item}]"
            else:
                parts.append(f"[{item}]")
        else:
            parts.append(str(item))
    return ".".join(parts)


def _suggest_missing_field_typo(missing_field: str, input_value: Any) -> str | None:
    """Suggest a likely typo when a required field is missing but a similar key exists."""
    if not isinstance(input_value, dict):
        return None
    unknown_keys = [key for key in input_value if isinstance(key, str)]
    matches = difflib.get_close_matches(missing_field, unknown_keys, n=1, cutoff=0.6)
    if not matches:
        return None
    return f"did you mean '{missing_field}'? (found '{matches[0]}')"


def format_config_validation_error(path: Path, exc: ValidationError) -> str:
    """Turn a pydantic ValidationError into a concise, user-facing message."""
    lines = [f"Invalid config file: {path}", ""]
    for err in exc.errors():
        loc = _format_error_loc(tuple(err["loc"]))
        msg = err["msg"]
        lines.append(f"  • {loc}: {msg}" if loc else f"  • {msg}")

        input_value = err.get("input")
        if err.get("type") == "missing":
            suggestion = _suggest_missing_field_typo(str(err["loc"][-1]), input_value)
            if suggestion:
                lines.append(f"    Hint: {suggestion}")
        elif input_value is not None and not isinstance(input_value, (dict, list)):
            lines.append(f"    Got: {input_value!r}")

    lines.extend(["", "Fix the file and try again, or run: klaude conf"])
    return "\n".join(lines)


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
                        model_alias=["my-model-legacy"],
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
    try:
        config_dict = yaml.safe_load(config_yaml)
    except yaml.YAMLError as e:
        message = (
            f"Invalid config file: {_schema.config_path}\n"
            f"\n"
            f"  • YAML parse error: {e}\n"
            f"\n"
            f"Fix the file and try again, or run: klaude conf"
        )
        raise ConfigValidationError(_schema.config_path, message) from e

    if config_dict is None:
        return None

    try:
        return _schema.UserConfig.model_validate(config_dict)
    except ValidationError as e:
        message = format_config_validation_error(_schema.config_path, e)
        raise ConfigValidationError(_schema.config_path, message) from e


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
