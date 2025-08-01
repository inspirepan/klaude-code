"""
Simple local configuration management for runtime options that don't need environment variables or file persistence
"""

from typing import Any, Dict

NO_STREAM_PRINT = "no_stream_print"


class SimpleConfig:
    """Simple configuration manager for runtime configuration options"""

    _config: Dict[str, Any] = {}

    @classmethod
    def set(cls, key: str, value: Any) -> None:
        """Set configuration value"""
        cls._config[key] = value

    @classmethod
    def get(cls, key: str, default: Any = None) -> Any:
        """Get configuration value"""
        return cls._config.get(key, default)

    @classmethod
    def has(cls, key: str) -> bool:
        """Check if configuration key exists"""
        return key in cls._config

    @classmethod
    def clear(cls) -> None:
        """Clear all configuration"""
        cls._config.clear()
