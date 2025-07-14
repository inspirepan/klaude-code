import os

from .model import ConfigModel, parse_json_string
from .source import ConfigSource


class EnvConfigSource(ConfigSource):
    """Environment variable configuration"""

    source = 'env'

    def __init__(self):
        super().__init__(self.source)
        self._env_map = {
            'api_key': 'API_KEY',
            'model_name': 'MODEL_NAME',
            'base_url': 'BASE_URL',
            'model_azure': 'MODEL_AZURE',
            'max_tokens': 'MAX_TOKENS',
            'context_window_threshold': 'CONTEXT_WINDOW_THRESHOLD',
            'extra_header': 'EXTRA_HEADER',
            'extra_body': 'EXTRA_BODY',
            'enable_thinking': 'ENABLE_THINKING',
            'api_version': 'API_VERSION',
            'theme': 'THEME',
        }
        self._load_env_config()

    def _load_env_config(self):
        """Load environment variables into config model"""
        config_data = {}
        for key, env_key in self._env_map.items():
            env_value = os.getenv(env_key)
            if env_value is not None:
                # Type conversion
                if key in ['model_azure', 'enable_thinking']:
                    config_data[key] = env_value.lower() in ['true', '1', 'yes', 'on']
                elif key in ['context_window_threshold', 'max_tokens']:
                    try:
                        config_data[key] = int(env_value)
                    except ValueError:
                        config_data[key] = None
                elif key in ['extra_header', 'extra_body']:
                    config_data[key] = parse_json_string(env_value)
                else:
                    config_data[key] = env_value

        self.config_model = ConfigModel(source=self.source, **config_data)
