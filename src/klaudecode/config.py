import json
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Union

from .tui import console, format_style

"""
Unified configuration management system
Priority: CLI args > Environment variables > Config file > Default values
"""

# Default value constants
DEFAULT_CONTEXT_WINDOW_THRESHOLD = 200000
DEFAULT_MODEL_NAME = "claude-sonnet-4-20250514"
DEFAULT_BASE_URL = "https://api.anthropic.com/v1/"
DEFAULT_MODEL_AZURE = False
DEFAULT_MAX_TOKENS = 8196
DEFAULT_EXTRA_HEADER = {}


class Config(ABC):
    """Base configuration class"""

    @abstractmethod
    def get(self, key: str) -> Optional[Union[str, bool, int]]:
        """Get configuration value"""
        pass

    @abstractmethod
    def get_source_name(self) -> str:
        """Get configuration source name"""
        pass


class ArgConfig(Config):
    """CLI argument configuration"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model_name: Optional[str] = None,
        base_url: Optional[str] = None,
        model_azure: Optional[bool] = None,
        max_tokens: Optional[int] = None,
        context_window_threshold: Optional[int] = None,
        extra_header: Optional[str] = None,
    ):
        self._args = {
            "api_key": api_key,
            "model_name": model_name,
            "base_url": base_url,
            "model_azure": model_azure,
            "max_tokens": max_tokens,
            "context_window_threshold": context_window_threshold,
            "extra_header": extra_header,
        }

    def get(self, key: str) -> Optional[Union[str, bool, int]]:
        return self._args.get(key) if self._args.get(key) is not None else None

    def get_source_name(self) -> str:
        return "cli"


class EnvConfig(Config):
    """Environment variable configuration"""

    def __init__(self):
        self._env_map = {
            "api_key": "API_KEY",
            "model_name": "MODEL_NAME",
            "base_url": "BASE_URL",
            "model_azure": "model_azure",
            "max_tokens": "MAX_TOKENS",
            "context_window_threshold": "CONTEXT_WINDOW_THRESHOLD",
            "extra_header": "EXTRA_HEADER",
        }

    def get(self, key: str) -> Optional[Union[str, bool, int]]:
        env_key = self._env_map.get(key)
        if not env_key:
            return None

        env_value = os.getenv(env_key)
        if env_value is None:
            return None

        # Type conversion
        if key == "model_azure":
            return env_value.lower() in ["true", "1", "yes", "on"]
        elif key in ["context_window_threshold", "max_tokens"]:
            try:
                return int(env_value)
            except ValueError:
                return None
        else:
            return env_value

    def get_source_name(self) -> str:
        return "env"


class GlobalConfig(Config):
    """Global configuration file"""

    def __init__(self):
        self._config_data = self._load_config()

    @staticmethod
    def get_config_path() -> Path:
        """Get configuration file path"""
        return Path.home() / ".klaude" / "config.json"

    def _load_config(self) -> Dict:
        """Load configuration file"""
        config_path = self.get_config_path()

        if not config_path.exists():
            return {}

        try:
            with open(config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            console.print(
                format_style(f"Warning: Failed to load config: {e}", "yellow")
            )
            return {}

    def get(self, key: str) -> Optional[Union[str, bool, int]]:
        return (
            self._config_data.get(key)
            if self._config_data.get(key) is not None
            else None
        )

    def get_source_name(self) -> str:
        return "config"


class DefaultConfig(Config):
    """Default configuration"""

    def __init__(self):
        self._defaults = {
            "api_key": None,
            "model_name": DEFAULT_MODEL_NAME,
            "base_url": DEFAULT_BASE_URL,
            "model_azure": DEFAULT_MODEL_AZURE,
            "max_tokens": DEFAULT_MAX_TOKENS,
            "context_window_threshold": DEFAULT_CONTEXT_WINDOW_THRESHOLD,
            "extra_header": DEFAULT_EXTRA_HEADER,
        }

    def get(self, key: str) -> Optional[Union[str, bool, int]]:
        return self._defaults.get(key)

    def get_source_name(self) -> str:
        return "default"


@dataclass
class ConfigValue:
    """Configuration value and source"""

    value: Optional[Union[str, bool, int]]
    source: str


class ConfigManager:
    """Global configuration manager"""

    def __init__(self, configs: List[Config]):
        self.configs = configs
        self.validate_required_config()

    def get_config_value(self, key: str) -> ConfigValue:
        """Get configuration value by priority order"""
        for config in self.configs:
            value = config.get(key)
            if value is not None:
                return ConfigValue(value=value, source=config.get_source_name())

        # Return empty value if no configuration has this value
        return ConfigValue(value=None, source="none")

    def get_api_key(self) -> Optional[str]:
        """Get API key"""
        result = self.get_config_value("api_key")
        return result.value

    def get_model_name(self) -> str:
        """Get model name"""
        result = self.get_config_value("model_name")
        return result.value or DEFAULT_MODEL_NAME

    def get_base_url(self) -> str:
        """Get base URL"""
        result = self.get_config_value("base_url")
        return result.value or DEFAULT_BASE_URL

    def get_model_azure(self) -> bool:
        """Get whether it's an Azure model"""
        result = self.get_config_value("model_azure")
        return result.value if result.value is not None else DEFAULT_MODEL_AZURE

    def get_max_tokens(self) -> int:
        """Get maximum token count"""
        result = self.get_config_value("max_tokens")
        return result.value or DEFAULT_MAX_TOKENS

    def get_context_window_threshold(self) -> int:
        """Get context window threshold"""
        result = self.get_config_value("context_window_threshold")
        return result.value or DEFAULT_CONTEXT_WINDOW_THRESHOLD

    def get_extra_header(self) -> Dict:
        """Get extra header as dictionary"""
        result = self.get_config_value("extra_header")
        if result.value is None:
            return DEFAULT_EXTRA_HEADER

        # If it's already a dictionary (from config file), return as is
        if isinstance(result.value, dict):
            return result.value

        # If it's a string (from CLI or env), parse as JSON
        if isinstance(result.value, str):
            try:
                return json.loads(result.value)
            except json.JSONDecodeError:
                console.print(
                    format_style(
                        f"Warning: Invalid JSON in extra_header: {result.value}",
                        "yellow",
                    )
                )
                return DEFAULT_EXTRA_HEADER

        return DEFAULT_EXTRA_HEADER

    def get_all_config_with_sources(self) -> Dict[str, ConfigValue]:
        """Get all configurations and their sources"""
        keys = [
            "api_key",
            "model_name",
            "base_url",
            "model_azure",
            "max_tokens",
            "context_window_threshold",
            "extra_header",
        ]
        result = {}
        for key in keys:
            config_value = self.get_config_value(key)
            if key == "api_key" and config_value.value:
                result[key] = ConfigValue(
                    value=config_value.value[:4] + "***" + config_value.value[-4:],
                    source=config_value.source,
                )
            else:
                result[key] = config_value

        return result

    def validate_required_config(self) -> None:
        """Validate required configuration"""
        api_key = self.get_api_key()
        if not api_key:
            raise ValueError(
                "API_KEY not found. Please set it via:\n"
                "1. Command line: --api-key your_key\n"
                "2. Environment variable: export API_KEY=your_key\n"
                "3. Config file: klaude-code config set api_key your_key"
            )

    def __rich__(self):
        """Return rich renderable object for configuration display"""
        from rich import box
        from rich.console import Group
        from rich.table import Table
        from rich.text import Text

        # Get all config values with sources
        config_data = self.get_all_config_with_sources()

        # Source display mapping
        source_display = {
            "cli": format_style("CLI", "bold gray"),
            "env": format_style("Env", "bold gray"),
            "config": format_style("Config", "bold gray"),
            "default": format_style("Default", "gray"),
            "none": format_style("None", "red"),
        }

        # Status display function
        def get_status(key, source):
            if key == "api_key":
                return (
                    format_style("✓", "green bold")
                    if config_data[key].value
                    else format_style("✗", "red bold")
                )
            elif source == "default":
                return format_style("✓", "blue bold")
            else:
                return format_style("✓", "green bold")

        # Configuration items with display names
        config_items_display = [
            (
                "api_key",
                "API Key",
                config_data["api_key"].value or format_style("Not Set", "red"),
            ),
            ("model_name", "Model", config_data["model_name"].value),
            ("base_url", "Base URL", config_data["base_url"].value),
            ("model_azure", "Azure Mode", str(config_data["model_azure"].value)),
            ("max_tokens", "Max Tokens", str(config_data["max_tokens"].value)),
            (
                "context_window_threshold",
                "Context Threshold",
                str(config_data["context_window_threshold"].value),
            ),
            (
                "extra_header",
                "Extra Header",
                str(config_data["extra_header"].value)
                if config_data["extra_header"].value
                else "{}",
            ),
        ]

        # Create table
        table = Table(
            padding=(0, 1), box=box.HORIZONTALS, show_header=False, show_edge=True
        )
        table.add_column(width=1, no_wrap=True)  # Status
        table.add_column(min_width=10, no_wrap=True)  # Setting name
        table.add_column(min_width=14)  # Value
        table.add_column()  # Source

        # Add rows
        for key, display_name, display_value in config_items_display:
            status = get_status(key, config_data[key].source)
            source = source_display[config_data[key].source]
            table.add_row(
                status,
                format_style(display_name, "bold gray"),
                display_value,
                f"from {source}",
            )

        # return Group(table, f" ⏺ [bold]Config path[/bold]: {GlobalConfig.get_config_path()}")
        return Group(
            "", Text(f"config path: {str(GlobalConfig.get_config_path())}"), table, ""
        )


def create_config_manager(
    api_key: Optional[str] = None,
    model_name: Optional[str] = None,
    base_url: Optional[str] = None,
    model_azure: Optional[bool] = None,
    max_tokens: Optional[int] = None,
    context_window_threshold: Optional[int] = None,
    extra_header: Optional[str] = None,
) -> ConfigManager:
    """Create configuration manager (create new instance each call to avoid state sharing)"""
    # Create configuration list in priority order
    configs = [
        ArgConfig(
            api_key,
            model_name,
            base_url,
            model_azure,
            max_tokens,
            context_window_threshold,
            extra_header,
        ),
        EnvConfig(),
        GlobalConfig(),
        DefaultConfig(),
    ]

    return ConfigManager(configs)


def open_config_file():
    config_path = GlobalConfig.get_config_path()
    if config_path.exists():
        console.print(
            format_style(
                f"Opening config file: {format_style(str(config_path), 'green')}",
                "green",
            )
        )
        import sys

        editor = os.getenv("EDITOR", "vi" if sys.platform != "darwin" else "open")
        os.system(f"{editor} {config_path}")
    else:
        console.print(format_style("Config file not found", "red"))


def create_example_config(config_path: Path):
    example_config = {
        "api_key": "your_api_key_here",
        "model_name": DEFAULT_MODEL_NAME,
        "base_url": DEFAULT_BASE_URL,
        "model_azure": DEFAULT_MODEL_AZURE,
        "max_tokens": DEFAULT_MAX_TOKENS,
        "context_window_threshold": DEFAULT_CONTEXT_WINDOW_THRESHOLD,
        "extra_header": DEFAULT_EXTRA_HEADER,
    }
    try:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(example_config, f, indent=2, ensure_ascii=False)
        console.print(
            format_style(f"Example config file created at: {config_path}", "green")
        )
        console.print("Please edit the file and set your actual API key.")
        return True
    except (IOError, OSError) as e:
        console.print(format_style(f"Error: Failed to create config file: {e}", "red"))
        return False


def edit_config_file():
    config_path = GlobalConfig.get_config_path()
    if not config_path.exists():
        create_example_config(config_path)
    open_config_file()
