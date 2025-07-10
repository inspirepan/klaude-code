from klaudecode.config.arg_source import ArgConfigSource


class TestArgConfigSource:
    """测试 ArgConfigSource 类"""

    def test_arg_config_source_initialization(self):
        """测试基本初始化"""
        source = ArgConfigSource()
        assert source.source == 'cli'
        assert source.config_model is not None

    def test_arg_config_source_with_values(self):
        """测试带参数的初始化"""
        source = ArgConfigSource(
            api_key='test_key',
            model_name='test_model',
            base_url='https://test.example.com',
            model_azure=True,
            max_tokens=2000,
            context_window_threshold=150000,
            enable_thinking=True,
            api_version='2024-04-01',
            theme='light',
        )

        assert source.get('api_key') == 'test_key'
        assert source.get('model_name') == 'test_model'
        assert source.get('base_url') == 'https://test.example.com'
        assert source.get('model_azure') is True
        assert source.get('max_tokens') == 2000
        assert source.get('context_window_threshold') == 150000
        assert source.get('enable_thinking') is True
        assert source.get('api_version') == '2024-04-01'
        assert source.get('theme') == 'light'

    def test_arg_config_source_none_values(self):
        """测试 None 值被忽略"""
        source = ArgConfigSource(api_key='test_key', model_name=None, max_tokens=None)

        assert source.get('api_key') == 'test_key'
        assert source.get('model_name') is None
        assert source.get('max_tokens') is None

    def test_arg_config_source_json_parsing(self):
        """测试 JSON 字符串解析"""
        source = ArgConfigSource(extra_header='{"Authorization": "Bearer token"}', extra_body='{"custom": "value"}')

        header_value = source.get('extra_header')
        body_value = source.get('extra_body')

        assert header_value == {'Authorization': 'Bearer token'}
        assert body_value == {'custom': 'value'}

    def test_arg_config_source_invalid_json(self):
        """测试无效 JSON 字符串处理"""
        source = ArgConfigSource(extra_header='invalid json', extra_body="{'not': 'valid'}")

        header_value = source.get('extra_header')
        body_value = source.get('extra_body')

        assert header_value == {}
        assert body_value == {}

    def test_arg_config_source_config_value_properties(self):
        """测试配置值的属性"""
        source = ArgConfigSource(api_key='test_key')

        config_value = source.config_model.api_key
        assert config_value.value == 'test_key'
        assert config_value.source == 'cli'
