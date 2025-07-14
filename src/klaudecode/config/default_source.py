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


class DefaultConfigSource(ConfigSource):
    """Default configuration"""

    source = 'default'

    def __init__(self):
        super().__init__(self.source)
        self.config_model = ConfigModel(
            source=self.source,
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
