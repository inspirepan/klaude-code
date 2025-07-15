import os
from unittest.mock import patch

from klaudecode.config.env_source import EnvConfigSource


class TestEnvConfigSource:
    """Test EnvConfigSource class"""

    def test_env_config_source_initialization(self):
        """Test basic initialization"""
        source = EnvConfigSource()
        assert source.source == 'env'
        assert source.config_model is not None

    @patch.dict(os.environ, {'API_KEY': 'test_api_key', 'MODEL_NAME': 'test_model', 'BASE_URL': 'https://test.example.com'})
    def test_env_config_source_string_values(self):
        """Test string environment variables"""
        source = EnvConfigSource()

        assert source.get('api_key') == 'test_api_key'
        assert source.get('model_name') == 'test_model'
        assert source.get('base_url') == 'https://test.example.com'

    @patch.dict(os.environ, {'MODEL_AZURE': 'true', 'ENABLE_THINKING': 'false'})
    def test_env_config_source_boolean_values(self):
        """Test boolean environment variables"""
        source = EnvConfigSource()

        assert source.get('model_azure') is True
        assert source.get('enable_thinking') is False

    @patch.dict(os.environ, {'MODEL_AZURE': '1', 'ENABLE_THINKING': '0'})
    def test_env_config_source_boolean_numeric(self):
        """Test numeric boolean environment variables"""
        source = EnvConfigSource()

        assert source.get('model_azure') is True
        assert source.get('enable_thinking') is False

    @patch.dict(os.environ, {'MODEL_AZURE': 'yes', 'ENABLE_THINKING': 'no'})
    def test_env_config_source_boolean_text(self):
        """Test text boolean environment variables"""
        source = EnvConfigSource()

        assert source.get('model_azure') is True
        assert source.get('enable_thinking') is False

    @patch.dict(os.environ, {'MODEL_AZURE': 'on', 'ENABLE_THINKING': 'off'})
    def test_env_config_source_boolean_on_off(self):
        """Test on/off boolean environment variables"""
        source = EnvConfigSource()

        assert source.get('model_azure') is True
        assert source.get('enable_thinking') is False

    @patch.dict(os.environ, {'MAX_TOKENS': '2000', 'CONTEXT_WINDOW_THRESHOLD': '150000'})
    def test_env_config_source_integer_values(self):
        """Test integer environment variables"""
        source = EnvConfigSource()

        assert source.get('max_tokens') == 2000
        assert source.get('context_window_threshold') == 150000

    @patch.dict(os.environ, {'MAX_TOKENS': 'invalid', 'CONTEXT_WINDOW_THRESHOLD': 'not_a_number'})
    def test_env_config_source_invalid_integer_values(self):
        """Test invalid integer environment variables"""
        source = EnvConfigSource()

        assert source.get('max_tokens') is None
        assert source.get('context_window_threshold') is None

    @patch.dict(os.environ, {'EXTRA_HEADER': '{"Authorization": "Bearer token"}', 'EXTRA_BODY': '{"custom": "value"}'})
    def test_env_config_source_json_values(self):
        """Test JSON environment variables"""
        source = EnvConfigSource()

        header_value = source.get('extra_header')
        body_value = source.get('extra_body')

        assert header_value == {'Authorization': 'Bearer token'}
        assert body_value == {'custom': 'value'}

    @patch.dict(os.environ, {'EXTRA_HEADER': 'invalid json', 'EXTRA_BODY': "{'not': 'valid'}"})
    def test_env_config_source_invalid_json_values(self):
        """Test invalid JSON environment variables"""
        source = EnvConfigSource()

        header_value = source.get('extra_header')
        body_value = source.get('extra_body')

        assert header_value == {}
        assert body_value == {}

    @patch.dict(os.environ, {}, clear=True)
    def test_env_config_source_no_environment_variables(self):
        """Test when no environment variables are set"""
        source = EnvConfigSource()

        assert source.get('api_key') is None
        assert source.get('model_name') is None
        assert source.get('model_azure') is None

    @patch.dict(os.environ, {'API_KEY': 'test_key', 'UNKNOWN_VAR': 'should_be_ignored'})
    def test_env_config_source_unknown_variables_ignored(self):
        """Test unknown environment variables are ignored"""
        source = EnvConfigSource()

        assert source.get('api_key') == 'test_key'
        assert source.get('unknown_var') is None

    @patch.dict(os.environ, {'API_KEY': 'test_key'})
    def test_env_config_source_config_value_properties(self):
        """Test config value properties"""
        source = EnvConfigSource()

        config_value = source.config_model.api_key
        assert config_value.value == 'test_key'
        assert config_value.source == 'env'
