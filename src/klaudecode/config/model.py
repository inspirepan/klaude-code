import json
from dataclasses import dataclass
from typing import Dict, Generic, Optional, TypeVar, Union

from pydantic import BaseModel
from rich.table import Table
from rich.text import Text

from ..tui import ColorStyle


def parse_json_string(value: Union[Dict, str]) -> Dict:
    """Parse JSON string to dict, return as-is if already dict"""
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            from ..tui import console

            console.print(Text(f'Warning: Invalid JSON string, using empty dict: {value}', style=ColorStyle.ERROR))
            return {}
    return {}


def mask_api_key(api_key: str) -> str:
    """Mask API key, showing first 5 and last 5 characters with asterisks in between"""
    if not api_key:
        return api_key

    if len(api_key) <= 10:
        # For short keys, show first few characters + asterisks
        visible_chars = min(3, len(api_key) // 2)
        return api_key[:visible_chars] + '*' * (len(api_key) - visible_chars)
    else:
        # For long keys, show first 5 + asterisks + last 5
        return api_key[:5] + '*' * (len(api_key) - 10) + api_key[-5:]


T = TypeVar('T')


@dataclass
class ConfigValue(Generic[T]):
    """Configuration value with source information"""

    value: Optional[T]
    source: str

    def __bool__(self) -> bool:
        return self.value is not None


config_source_style_dict = {
    'default': ColorStyle.HINT,
    'env': ColorStyle.INFO.bold,
    'cli': ColorStyle.INFO.bold,
    '--config': ColorStyle.SUCCESS.bold,
    'config': ColorStyle.TOOL_NAME,
}


class ConfigModel(BaseModel):
    """Pydantic model for configuration with sources"""

    api_key: Optional[ConfigValue[str]] = None
    model_name: Optional[ConfigValue[str]] = None
    base_url: Optional[ConfigValue[str]] = None
    model_azure: Optional[ConfigValue[bool]] = None
    max_tokens: Optional[ConfigValue[int]] = None
    context_window_threshold: Optional[ConfigValue[int]] = None
    extra_header: Optional[ConfigValue[Union[Dict, str]]] = None
    extra_body: Optional[ConfigValue[Union[Dict, str]]] = None
    enable_thinking: Optional[ConfigValue[bool]] = None
    api_version: Optional[ConfigValue[str]] = None
    theme: Optional[ConfigValue[str]] = None

    def __init__(self, source: str = 'unknown', **data):
        # Convert plain values to ConfigValue objects with source
        config_values = {}
        for key, value in data.items():
            if value is not None:
                config_values[key] = ConfigValue(value=value, source=source)
        super().__init__(**config_values)

    @classmethod
    def model_validate(cls, obj, *, strict=None, from_attributes=None, context=None):
        """Override model_validate to handle ConfigValue dict format"""
        if isinstance(obj, dict):
            # Handle the case where obj contains ConfigValue dicts
            config_values = {}
            for key, value in obj.items():
                if isinstance(value, dict) and 'value' in value and 'source' in value:
                    config_values[key] = ConfigValue(value=value['value'], source=value['source'])
                else:
                    config_values[key] = value
            # Create instance directly without going through __init__
            instance = cls.__new__(cls)
            BaseModel.__init__(instance, **config_values)
            return instance
        return super().model_validate(obj, strict=strict, from_attributes=from_attributes, context=context)

    def __rich__(self):
        """Rich display for configuration model"""
        table = Table.grid(padding=(0, 1), expand=True)
        table.add_column(width=1, no_wrap=True)  # Status
        table.add_column(
            ratio=1,
            no_wrap=True,
        )  # Setting name
        table.add_column(ratio=4, overflow='fold')  # Value
        table.add_column(ratio=1)  # Source

        config_items = [
            ('api_key', 'API Key'),
            ('model_name', 'Model'),
            ('base_url', 'Base URL'),
            ('model_azure', 'Azure Mode'),
            ('max_tokens', 'Max Tokens'),
            ('context_window_threshold', 'Context Threshold'),
            ('extra_header', 'Extra Header'),
            ('extra_body', 'Extra Body'),
            ('enable_thinking', 'Extended Thinking'),
            ('api_version', 'API Version'),
            ('theme', 'Theme'),
        ]

        for key, display_name in config_items:
            config_value = getattr(self, key, None)
            if config_value and config_value.value is not None:
                status = Text('✓', style=ColorStyle.SUCCESS)
                value_str = str(config_value.value)

                # Mask API key for security
                if key == 'api_key' and value_str:
                    value = mask_api_key(value_str)
                else:
                    value = value_str

                # Use a default style for unknown sources
                source_style = config_source_style_dict.get(config_value.source, ColorStyle.INFO)
                source = Text.assemble('from ', (config_value.source, source_style))
            else:
                status = Text('✗', style=ColorStyle.ERROR.bold)
                value = Text('Not Set', style=ColorStyle.ERROR)
                source = ''
            table.add_row(
                status,
                Text(display_name, style=ColorStyle.INFO),
                value,
                source,
            )
        return table
