"""Built-in provider and model configurations.

These configurations allow users to start using klaude by simply setting
environment variables (ANTHROPIC_API_KEY, OPENAI_API_KEY, etc.) without
manually configuring providers.
"""

from dataclasses import dataclass
from functools import lru_cache
from importlib import resources
from typing import TYPE_CHECKING, Any

import yaml

if TYPE_CHECKING:
    from klaude_code.config.config import Config


@dataclass(frozen=True)
class ApiKeyInfo:
    """Information about a supported API key."""

    env_var: str
    name: str
    description: str


# All supported API keys with their metadata
SUPPORTED_API_KEYS: tuple[ApiKeyInfo, ...] = (
    ApiKeyInfo("ANTHROPIC_API_KEY", "Anthropic", "Anthropic API key"),
    ApiKeyInfo("OPENAI_API_KEY", "OpenAI", "OpenAI API key"),
    ApiKeyInfo("OPENROUTER_API_KEY", "OpenRouter", "OpenRouter API key"),
    ApiKeyInfo("GOOGLE_API_KEY", "Google Gemini", "Google API key (Gemini)"),
    ApiKeyInfo("DEEPSEEK_API_KEY", "DeepSeek", "DeepSeek API key"),
    ApiKeyInfo("MOONSHOT_API_KEY", "Moonshot Kimi", "Moonshot API key (Kimi)"),
)

# For backwards compatibility
SUPPORTED_API_KEY_ENVS = [k.env_var for k in SUPPORTED_API_KEYS]


@lru_cache(maxsize=1)
def _load_builtin_yaml() -> dict[str, Any]:
    """Load the built-in config YAML asset."""
    assets = resources.files("klaude_code.config.assets")
    yaml_content = (assets / "builtin_config.yaml").read_text()
    data: dict[str, Any] = yaml.safe_load(yaml_content)
    return data


def get_builtin_config() -> "Config":
    """Load built-in configuration from YAML asset."""
    # Import here to avoid circular import
    from klaude_code.config.config import Config

    data = _load_builtin_yaml()
    return Config.model_validate(data)
