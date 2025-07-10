import json
from pathlib import Path

from rich.text import Text

from ..tui import ColorStyle, console
from ..utils.exception import format_exception
from .model import ConfigModel
from .source import ConfigSource


class FileArgConfigSource(ConfigSource):
    """Configuration from CLI specified file"""

    def __init__(self, config_file: str):
        super().__init__('--config')
        self.config_file = config_file
        self._load_config()

    def _load_config(self):
        """Load configuration file into config model"""
        config_path = Path(self.config_file)
        if not config_path.exists():
            console.print(Text(f'Warning: Config file not found: {config_path}', style=ColorStyle.ERROR))
            self.config_model = ConfigModel(source='--config')
            return

        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config_data = json.load(f)
                # Filter only valid ConfigModel fields
                valid_fields = {k for k in ConfigModel.model_fields.keys()}
                filtered_data = {k: v for k, v in config_data.items() if k in valid_fields}
                self.config_model = ConfigModel(source='--config', **filtered_data)
        except (json.JSONDecodeError, IOError) as e:
            console.print(Text(f'Warning: Failed to load config file {config_path}: {format_exception(e)}', style=ColorStyle.ERROR))
            self.config_model = ConfigModel(source='--config')
