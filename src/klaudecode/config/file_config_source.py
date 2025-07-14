import json
import os
from pathlib import Path
from typing import Optional

from rich.text import Text

from ..tui import ColorStyle, console
from ..utils.exception import format_exception
from .default_source import (
    DEFAULT_API_VERSION,
    DEFAULT_BASE_URL,
    DEFAULT_CONTEXT_WINDOW_THRESHOLD,
    DEFAULT_ENABLE_THINKING,
    DEFAULT_EXTRA_BODY,
    DEFAULT_EXTRA_HEADER,
    DEFAULT_MAX_TOKENS,
    DEFAULT_MODEL_AZURE,
    DEFAULT_MODEL_NAME,
    DEFAULT_THEME,
)
from .model import ConfigModel
from .source import ConfigSource


def resolve_config_path(config_input: str) -> Path:
    """
    Resolve config path from input string.

    If input is a full path, use it directly.
    If input is a short name like 'anthropic', resolve to ~/.klaude/config_anthropic.json
    """
    config_path = Path(config_input)

    # If it's already an absolute path or relative path with directory separators, use as-is
    if config_path.is_absolute() or '/' in config_input or '\\' in config_input:
        return config_path

    # If it's just a name without extension, treat as short name
    if not config_input.endswith('.json'):
        return Path.home() / '.klaude' / f'config_{config_input}.json'

    # If it's a filename ending with .json, put it in ~/.klaude/
    return Path.home() / '.klaude' / config_input


def get_default_config_path() -> Path:
    """Get default global configuration file path"""
    return Path.home() / '.klaude' / 'config.json'


class FileConfigSource(ConfigSource):
    """Configuration from file (either global config.json or CLI specified file)"""

    def __init__(self, config_file: Optional[str] = None, source_name: Optional[str] = None):
        """
        Initialize file config source

        Args:
            config_file: Path to config file. If None, uses default global config
            source_name: Name for this config source. If None, auto-determined from config path
        """
        self.config_file = config_file
        self.config_path = self._determine_config_path()

        # Auto-determine source name if not provided
        if source_name is None:
            source_name = self._determine_source_name()

        super().__init__(source_name)
        self._load_config()

    def _determine_source_name(self) -> str:
        """Determine source name based on config file path"""
        config_path = self.config_path

        # Check if it's the default global config
        if config_path == get_default_config_path():
            return 'global'

        # Check if it's in ~/.klaude/ directory with config_xxx.json pattern
        if config_path.parent == Path.home() / '.klaude' and config_path.name.startswith('config_') and config_path.name.endswith('.json'):
            # Extract xxx from config_xxx.json
            return config_path.name[7:-5]  # Remove 'config_' prefix and '.json' suffix

        # For other paths, use the filename
        return config_path.name

    def _determine_config_path(self) -> Path:
        """Determine the config file path"""
        if self.config_file is None:
            return get_default_config_path()
        return resolve_config_path(self.config_file)

    def _load_config(self):
        """Load configuration file into config model"""
        if not self.config_path.exists():
            self.config_model = ConfigModel(source=self.source)
            return

        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                config_data = json.load(f)
                # Filter only valid ConfigModel fields
                valid_fields = {k for k in ConfigModel.model_fields.keys()}
                filtered_data = {k: v for k, v in config_data.items() if k in valid_fields}
                self.config_model = ConfigModel(source=self.source, **filtered_data)
        except (json.JSONDecodeError, IOError) as e:
            console.print(Text(f'Warning: Failed to load config file {self.config_path}: {format_exception(e)}', style=ColorStyle.ERROR))
            self.config_model = ConfigModel(source=self.source)

    @classmethod
    def create_global_config_source(cls):
        """Create a global config source instance"""
        return cls(config_file=None)

    @classmethod
    def create_cli_config_source(cls, config_file: str):
        """Create a CLI config source instance"""
        return cls(config_file=config_file)

    @classmethod
    def get_config_path(cls) -> Path:
        """Get default configuration file path (for backward compatibility)"""
        return get_default_config_path()

    @classmethod
    def open_config_file(cls, config_path: Optional[Path] = None):
        """Open the configuration file in the default editor"""
        if config_path is None:
            config_path = get_default_config_path()

        if config_path.exists():
            console.print(Text(f'Opening config file: {str(config_path)}', style=ColorStyle.SUCCESS))
            import sys

            editor = os.getenv('EDITOR', 'vi' if sys.platform != 'darwin' else 'open')
            os.system(f'{editor} {config_path}')
        else:
            console.print(Text('Config file not found', style=ColorStyle.ERROR))

    @classmethod
    def create_example_config(cls, config_path: Optional[Path] = None):
        """Create an example configuration file"""
        if config_path is None:
            config_path = get_default_config_path()

        example_config = {
            'api_key': 'your_api_key_here',
            'model_name': DEFAULT_MODEL_NAME,
            'base_url': DEFAULT_BASE_URL,
            'model_azure': DEFAULT_MODEL_AZURE,
            'max_tokens': DEFAULT_MAX_TOKENS,
            'context_window_threshold': DEFAULT_CONTEXT_WINDOW_THRESHOLD,
            'extra_header': DEFAULT_EXTRA_HEADER,
            'extra_body': DEFAULT_EXTRA_BODY,
            'enable_thinking': DEFAULT_ENABLE_THINKING,
            'api_version': DEFAULT_API_VERSION,
            'theme': DEFAULT_THEME,
        }
        try:
            config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(example_config, f, indent=2, ensure_ascii=False)
            console.print(Text(f'Example config file created at: {config_path}', style=ColorStyle.SUCCESS))
            console.print(Text('Please edit the file and set your actual API key.'))
            return True
        except (IOError, OSError) as e:
            console.print(Text(f'Error: Failed to create config file: {format_exception(e)}', style=ColorStyle.ERROR))
            return False

    @classmethod
    def edit_config_file(cls, config_path: Optional[Path] = None):
        """Edit the configuration file, creating one if it doesn't exist"""
        if config_path is None:
            config_path = get_default_config_path()

        if not config_path.exists():
            cls.create_example_config(config_path)
        cls.open_config_file(config_path)
