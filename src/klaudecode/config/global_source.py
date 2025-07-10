import json
import os
from pathlib import Path

from rich.text import Text

from ..tui import ColorStyle, console
from ..utils.exception import format_exception
from .model import ConfigModel
from .source import ConfigSource

# Default value constants
DEFAULT_CONTEXT_WINDOW_THRESHOLD = 200000
DEFAULT_MODEL_NAME = 'claude-sonnet-4-20250514'
DEFAULT_BASE_URL = 'https://api.anthropic.com/v1/'
DEFAULT_MODEL_AZURE = False
DEFAULT_MAX_TOKENS = 32000
DEFAULT_EXTRA_HEADER = {}
DEFAULT_EXTRA_BODY = {}
DEFAULT_ENABLE_THINKING = False
DEFAULT_API_VERSION = '2024-03-01-preview'
DEFAULT_THEME = 'dark'  # Supported themes: 'light', 'dark', 'light_ansi', 'dark_ansi'


class GlobalConfigSource(ConfigSource):
    """Global configuration file"""

    def __init__(self):
        super().__init__('config')
        self._load_config()

    @staticmethod
    def get_config_path() -> Path:
        """Get configuration file path"""
        return Path.home() / '.klaude' / 'config.json'

    def _load_config(self):
        """Load configuration file into config model"""
        config_path = self.get_config_path()
        if not config_path.exists():
            self.config_model = ConfigModel(source='config')
            return

        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config_data = json.load(f)
                # Filter only valid ConfigModel fields
                valid_fields = {k for k in ConfigModel.model_fields.keys()}
                filtered_data = {k: v for k, v in config_data.items() if k in valid_fields}
                self.config_model = ConfigModel(source='config', **filtered_data)
        except (json.JSONDecodeError, IOError) as e:
            console.print(Text(f'Warning: Failed to load config: {format_exception(e)}', style=ColorStyle.ERROR))
            self.config_model = ConfigModel(source='config')

    @classmethod
    def open_config_file(cls):
        """Open the configuration file in the default editor"""
        config_path = cls.get_config_path()
        if config_path.exists():
            console.print(Text(f'Opening config file: {str(config_path)}', style=ColorStyle.SUCCESS))
            import sys

            editor = os.getenv('EDITOR', 'vi' if sys.platform != 'darwin' else 'open')
            os.system(f'{editor} {config_path}')
        else:
            console.print(Text('Config file not found', style=ColorStyle.ERROR))

    @classmethod
    def create_example_config(cls, config_path: Path = None):
        """Create an example configuration file"""
        if config_path is None:
            config_path = cls.get_config_path()

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
    def edit_config_file(cls):
        """Edit the configuration file, creating one if it doesn't exist"""
        config_path = cls.get_config_path()
        if not config_path.exists():
            cls.create_example_config(config_path)
        cls.open_config_file()
