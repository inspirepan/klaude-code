import os
from unittest.mock import patch


from klaudecode.config.env_source import EnvConfigSource


class TestEnvConfigSource:
    """测试 EnvConfigSource 类"""

    def test_env_config_source_initialization(self):
        """测试基本初始化"""
        source = EnvConfigSource()
        assert source.source == 'env'
        assert source.config_model is not None

    @patch.dict(os.environ, {'API_KEY': 'test_api_key', 'MODEL_NAME': 'test_model', 'BASE_URL': 'https://test.example.com'})
    def test_env_config_source_string_values(self):
        """测试字符串环境变量"""
        source = EnvConfigSource()

        assert source.get('api_key') == 'test_api_key'
        assert source.get('model_name') == 'test_model'
        assert source.get('base_url') == 'https://test.example.com'

    @patch.dict(os.environ, {'MODEL_AZURE': 'true', 'ENABLE_THINKING': 'false'})
    def test_env_config_source_boolean_values(self):
        """测试布尔环境变量"""
        source = EnvConfigSource()

        assert source.get('model_azure') is True
        assert source.get('enable_thinking') is False

    @patch.dict(os.environ, {'MODEL_AZURE': '1', 'ENABLE_THINKING': '0'})
    def test_env_config_source_boolean_numeric(self):
        """测试数字形式的布尔环境变量"""
        source = EnvConfigSource()

        assert source.get('model_azure') is True
        assert source.get('enable_thinking') is False

    @patch.dict(os.environ, {'MODEL_AZURE': 'yes', 'ENABLE_THINKING': 'no'})
    def test_env_config_source_boolean_text(self):
        """测试文本形式的布尔环境变量"""
        source = EnvConfigSource()

        assert source.get('model_azure') is True
        assert source.get('enable_thinking') is False

    @patch.dict(os.environ, {'MODEL_AZURE': 'on', 'ENABLE_THINKING': 'off'})
    def test_env_config_source_boolean_on_off(self):
        """测试 on/off 形式的布尔环境变量"""
        source = EnvConfigSource()

        assert source.get('model_azure') is True
        assert source.get('enable_thinking') is False

    @patch.dict(os.environ, {'MAX_TOKENS': '2000', 'CONTEXT_WINDOW_THRESHOLD': '150000'})
    def test_env_config_source_integer_values(self):
        """测试整数环境变量"""
        source = EnvConfigSource()

        assert source.get('max_tokens') == 2000
        assert source.get('context_window_threshold') == 150000

    @patch.dict(os.environ, {'MAX_TOKENS': 'invalid', 'CONTEXT_WINDOW_THRESHOLD': 'not_a_number'})
    def test_env_config_source_invalid_integer_values(self):
        """测试无效整数环境变量"""
        source = EnvConfigSource()

        assert source.get('max_tokens') is None
        assert source.get('context_window_threshold') is None

    @patch.dict(os.environ, {'EXTRA_HEADER': '{"Authorization": "Bearer token"}', 'EXTRA_BODY': '{"custom": "value"}'})
    def test_env_config_source_json_values(self):
        """测试 JSON 环境变量"""
        source = EnvConfigSource()

        header_value = source.get('extra_header')
        body_value = source.get('extra_body')

        assert header_value == {'Authorization': 'Bearer token'}
        assert body_value == {'custom': 'value'}

    @patch.dict(os.environ, {'EXTRA_HEADER': 'invalid json', 'EXTRA_BODY': "{'not': 'valid'}"})
    def test_env_config_source_invalid_json_values(self):
        """测试无效 JSON 环境变量"""
        source = EnvConfigSource()

        header_value = source.get('extra_header')
        body_value = source.get('extra_body')

        assert header_value == {}
        assert body_value == {}

    @patch.dict(os.environ, {}, clear=True)
    def test_env_config_source_no_environment_variables(self):
        """测试没有环境变量时"""
        source = EnvConfigSource()

        assert source.get('api_key') is None
        assert source.get('model_name') is None
        assert source.get('model_azure') is None

    @patch.dict(os.environ, {'API_KEY': 'test_key', 'UNKNOWN_VAR': 'should_be_ignored'})
    def test_env_config_source_unknown_variables_ignored(self):
        """测试未知环境变量被忽略"""
        source = EnvConfigSource()

        assert source.get('api_key') == 'test_key'
        assert source.get('unknown_var') is None

    @patch.dict(os.environ, {'API_KEY': 'test_key'})
    def test_env_config_source_config_value_properties(self):
        """测试配置值的属性"""
        source = EnvConfigSource()

        config_value = source.config_model.api_key
        assert config_value.value == 'test_key'
        assert config_value.source == 'env'
