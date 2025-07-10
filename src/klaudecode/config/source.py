from typing import Optional, Union

from .model import ConfigModel


class ConfigSource:
    def __init__(self, source: str):
        self.source = source
        self.config_model: ConfigModel = None

    def get(self, key: str) -> Optional[Union[str, bool, int]]:
        """Get configuration value"""
        config_value = getattr(self.config_model, key, None)
        return config_value.value if config_value else None

    def get_source_name(self) -> str:
        """Get configuration source name"""
        return self.source

    def get_config_model(self) -> ConfigModel:
        """Get the internal config model"""
        return self.config_model
