from typing import List, Optional, Union

from rich import box
from rich.console import Group
from rich.panel import Panel
from rich.text import Text

from ..tui import ColorStyle, console
from .arg_source import ArgConfigSource
from .default_source import DefaultConfigSource
from .env_source import EnvConfigSource
from .file_config_source import FileConfigSource, get_default_config_path
from .model import ConfigModel, ConfigValue
from .source import ConfigSource


class ConfigManager:
    """Configuration manager that merges multiple config sources with priority"""

    def __init__(self, sources: List[ConfigSource]):
        # Sources in priority order (higher index = higher priority)
        self.sources = sources
        self._merged_config_model = self._merge_config_models()
        self._config_path = self._determine_config_path()
        self._validate_api_key()

    def _determine_config_path(self):
        """Determine the primary config file path from sources"""
        # Find the FileConfigSource and use its path
        for source in self.sources:
            if isinstance(source, FileConfigSource):
                return source.config_path

        # Fallback to default if no FileConfigSource found
        return get_default_config_path()

    def _merge_config_models(self) -> ConfigModel:
        """Merge all configuration models from sources"""
        merged_config = {}

        # Merge all sources (later sources override earlier ones)
        for source in self.sources:
            if source.config_model:
                for field_name in ConfigModel.model_fields.keys():
                    config_value = getattr(source.config_model, field_name, None)
                    if config_value and config_value.value is not None:
                        merged_config[field_name] = config_value

        # Create final config model with preserved source information
        final_model = ConfigModel()
        for key, config_value in merged_config.items():
            setattr(final_model, key, config_value)

        return final_model

    def _validate_api_key(self):
        """Validate that API key is provided and not from default source"""
        api_key_config = self._merged_config_model.api_key
        if not api_key_config or not api_key_config.value or api_key_config.source == 'default':
            console.print(Text('Error: API key not set', style='red bold'))
            console.print()
            console.print(Text('Please set your API key using one of the following methods:'))
            console.print(Text('- Command line: --api-key YOUR_API_KEY'))
            console.print(Text('- Environment: export API_KEY=YOUR_API_KEY'))
            console.print(Text("- Config file: Run 'klaude config edit' to configure"))
            import sys

            sys.exit(1)

    def get_config_model(self) -> ConfigModel:
        """Get merged configuration model from all sources"""
        return self._merged_config_model

    def __rich__(self):
        return Group(
            Text.assemble('config path: ', (str(self._config_path), ColorStyle.SUCCESS)),
            Panel.fit(self.get_config_model(), box=box.ROUNDED, border_style=ColorStyle.LINE),
        )

    def get(self, key: str) -> Optional[Union[str, bool, int]]:
        """Get configuration value with priority resolution"""
        config_value = getattr(self._merged_config_model, key, None)
        return config_value.value if config_value else None

    def get_value_with_source(self, key: str) -> Optional[ConfigValue]:
        """Get configuration value with source information"""
        return getattr(self._merged_config_model, key, None)

    @classmethod
    def setup(
        cls,
        api_key: Optional[str] = None,
        model_name: Optional[str] = None,
        base_url: Optional[str] = None,
        model_azure: Optional[bool] = None,
        max_tokens: Optional[int] = None,
        context_window_threshold: Optional[int] = None,
        extra_header: Optional[str] = None,
        extra_body: Optional[str] = None,
        enable_thinking: Optional[bool] = None,
        api_version: Optional[str] = None,
        theme: Optional[str] = None,
        config_file: Optional[str] = None,
    ) -> 'ConfigManager':
        """Create a ConfigManager with all configuration sources

        Args:
            CLI arguments that will be passed to ArgConfigSource
            config_file: Path to configuration file specified via CLI

        Returns:
            ConfigManager with sources in priority order: Default < Environment < File Config < CLI Args
        """
        sources = [
            DefaultConfigSource(),
            EnvConfigSource(),
        ]

        # Add file config source - either CLI specified or global
        if config_file:
            sources.append(FileConfigSource.create_cli_config_source(config_file))
        else:
            sources.append(FileConfigSource.create_global_config_source())

        # CLI arguments have the highest priority
        sources.append(
            ArgConfigSource(
                api_key=api_key,
                model_name=model_name,
                base_url=base_url,
                model_azure=model_azure,
                max_tokens=max_tokens,
                context_window_threshold=context_window_threshold,
                extra_header=extra_header,
                extra_body=extra_body,
                enable_thinking=enable_thinking,
                api_version=api_version,
                theme=theme,
            )
        )

        return cls(sources)
