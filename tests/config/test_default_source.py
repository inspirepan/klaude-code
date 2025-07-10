from klaudecode.config.default_source import DefaultConfigSource
from klaudecode.config.global_source import (
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


class TestDefaultConfigSource:
    """测试 DefaultConfigSource 类"""

    def test_default_config_source_initialization(self):
        """测试默认配置源初始化"""
        source = DefaultConfigSource()
        assert source.source == 'default'
        assert source.config_model is not None

    def test_default_config_source_values(self):
        """测试默认配置值"""
        source = DefaultConfigSource()

        # API key 应该为 None（需要用户设置）
        assert source.get('api_key') is None

        # 其他值应该是默认值
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
        """测试配置值的属性"""
        source = DefaultConfigSource()

        # 测试非 None 值的 ConfigValue 属性
        model_name_config = source.config_model.model_name
        assert model_name_config.value == DEFAULT_MODEL_NAME
        assert model_name_config.source == 'default'

        base_url_config = source.config_model.base_url
        assert base_url_config.value == DEFAULT_BASE_URL
        assert base_url_config.source == 'default'

        # API key 应该为 None
        assert source.config_model.api_key is None

    def test_default_values_consistency(self):
        """测试默认值常量的一致性"""
        source = DefaultConfigSource()

        # 确保 DefaultConfigSource 使用的值与导入的常量一致
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
