from klaudecode.config.model import ConfigModel
from klaudecode.config.source import ConfigSource


class TestConfigSource:
    """Test ConfigSource base class"""

    def test_config_source_initialization(self):
        """Test ConfigSource initialization"""
        source = ConfigSource('test')
        assert source.source == 'test'
        assert source.config_model is None

    def test_get_source_name(self):
        """Test getting source name"""
        source = ConfigSource('test_source')
        assert source.get_source_name() == 'test_source'

    def test_get_config_model(self):
        """Test getting config model"""
        source = ConfigSource('test')
        config_model = ConfigModel(source='test', api_key='test_key')
        source.config_model = config_model

        assert source.get_config_model() == config_model

    def test_get_value_with_config(self):
        """Test getting value from config model"""
        source = ConfigSource('test')
        source.config_model = ConfigModel(source='test', api_key='test_key')

        assert source.get('api_key') == 'test_key'

    def test_get_value_without_config(self):
        """Test getting value when no config model"""
        source = ConfigSource('test')
        assert source.get('api_key') is None

    def test_get_nonexistent_key(self):
        """Test getting non-existent key"""
        source = ConfigSource('test')
        source.config_model = ConfigModel(source='test', api_key='test_key')

        assert source.get('nonexistent') is None
