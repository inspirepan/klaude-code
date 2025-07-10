from .global_source import (
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


class DefaultConfigSource(ConfigSource):
    """Default configuration"""

    def __init__(self):
        super().__init__('default')
        self.config_model = ConfigModel(
            source='default',
            api_key=None,
            model_name=DEFAULT_MODEL_NAME,
            base_url=DEFAULT_BASE_URL,
            model_azure=DEFAULT_MODEL_AZURE,
            api_version=DEFAULT_API_VERSION,
            max_tokens=DEFAULT_MAX_TOKENS,
            context_window_threshold=DEFAULT_CONTEXT_WINDOW_THRESHOLD,
            extra_header=DEFAULT_EXTRA_HEADER,
            extra_body=DEFAULT_EXTRA_BODY,
            enable_thinking=DEFAULT_ENABLE_THINKING,
            theme=DEFAULT_THEME,
        )
