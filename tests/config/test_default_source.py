from klaudecode.config.default_source import (
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
    DefaultConfigSource,
)


class TestDefaultConfigSource:
    """Test DefaultConfigSource class"""

    def test_default_config_source_initialization(self):
        """Test default config source initialization"""
        source = DefaultConfigSource()
        assert source.source == 'default'
        assert source.config_model is not None

    def test_default_config_source_values(self):
        """Test default config values"""
        source = DefaultConfigSource()

        # API key should be None (needs to be set by user)
        assert source.get('api_key') is None

        # Other values should be default values
        assert source.get('model_name') == DEFAULT_MODEL_NAME
        assert source.get('base_url') == DEFAULT_BASE_URL
        assert source.get('model_azure') == DEFAULT_MODEL_AZURE
        assert source.get('api_version') == DEFAULT_API_VERSION
        assert source.get('max_tokens') == DEFAULT_MAX_TOKENS
        assert source.get('context_window_threshold') == DEFAULT_CONTEXT_WINDOW_THRESHOLD
        assert source.get('extra_header') == DEFAULT_EXTRA_HEADER
        assert source.get('extra_body') == DEFAULT_EXTRA_BODY
        assert source.get('enable_thinking') == DEFAULT_ENABLE_THINKING
        assert source.get('theme') == DEFAULT_THEME

    def test_default_config_source_config_value_properties(self):
        """Test config value properties"""
        source = DefaultConfigSource()

        # Test non-None ConfigValue properties
        model_name_config = source.config_model.model_name
        assert model_name_config.value == DEFAULT_MODEL_NAME
        assert model_name_config.source == 'default'

        base_url_config = source.config_model.base_url
        assert base_url_config.value == DEFAULT_BASE_URL
        assert base_url_config.source == 'default'

        # API key should be None
        assert source.config_model.api_key is None

    def test_default_values_consistency(self):
        """Test consistency of default value constants"""
        source = DefaultConfigSource()

        # Ensure DefaultConfigSource uses values consistent with imported constants
        assert source.get('model_name') == DEFAULT_MODEL_NAME
        assert source.get('base_url') == DEFAULT_BASE_URL
        assert source.get('model_azure') == DEFAULT_MODEL_AZURE
        assert source.get('api_version') == DEFAULT_API_VERSION
        assert source.get('max_tokens') == DEFAULT_MAX_TOKENS
        assert source.get('context_window_threshold') == DEFAULT_CONTEXT_WINDOW_THRESHOLD
        assert source.get('extra_header') == DEFAULT_EXTRA_HEADER
        assert source.get('extra_body') == DEFAULT_EXTRA_BODY
        assert source.get('enable_thinking') == DEFAULT_ENABLE_THINKING
        assert source.get('theme') == DEFAULT_THEME
