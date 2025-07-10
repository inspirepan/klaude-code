from klaudecode.config.source import ConfigSource
from klaudecode.config.model import ConfigModel


class TestConfigSource:
    """测试 ConfigSource 基类"""

    def test_config_source_initialization(self):
        """测试 ConfigSource 初始化"""
        source = ConfigSource('test')
        assert source.source == 'test'
        assert source.config_model is None

    def test_get_source_name(self):
        """测试获取源名称"""
        source = ConfigSource('test_source')
        assert source.get_source_name() == 'test_source'

    def test_get_config_model(self):
        """测试获取配置模型"""
        source = ConfigSource('test')
        config_model = ConfigModel(source='test', api_key='test_key')
        source.config_model = config_model

        assert source.get_config_model() == config_model

    def test_get_value_with_config(self):
        """测试从配置模型获取值"""
        source = ConfigSource('test')
        source.config_model = ConfigModel(source='test', api_key='test_key')

        assert source.get('api_key') == 'test_key'

    def test_get_value_without_config(self):
        """测试没有配置模型时获取值"""
        source = ConfigSource('test')
        assert source.get('api_key') is None

    def test_get_nonexistent_key(self):
        """测试获取不存在的键"""
        source = ConfigSource('test')
        source.config_model = ConfigModel(source='test', api_key='test_key')

        assert source.get('nonexistent') is None
