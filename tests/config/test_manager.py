import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from klaudecode.config.arg_source import ArgConfigSource
from klaudecode.config.default_source import DefaultConfigSource
from klaudecode.config.env_source import EnvConfigSource
from klaudecode.config.file_config_source import FileConfigSource
from klaudecode.config.manager import ConfigManager


class TestConfigManager:
    """Test ConfigManager class"""

    def test_config_manager_initialization(self):
        """Test ConfigManager basic initialization"""
        sources = [DefaultConfigSource()]

        with patch.object(ConfigManager, '_validate_api_key'):
            manager = ConfigManager(sources)
            assert manager.sources == sources
            assert manager._merged_config_model is not None

    def test_config_manager_merge_priority(self):
        """Test configuration merge priority"""
        # Create multiple config sources, later ones have higher priority
        sources = [
            DefaultConfigSource(),  # model_name: claude-sonnet-4-20250514
            ArgConfigSource(model_name='arg_model'),  # model_name: arg_model
        ]

        with patch.object(ConfigManager, '_validate_api_key'):
            manager = ConfigManager(sources)

            # ArgConfigSource should have higher priority
            assert manager.get('model_name') == 'arg_model'

    def test_config_manager_get_value_with_source(self):
        """Test getting configuration value with source information"""
        sources = [
            DefaultConfigSource(),
            ArgConfigSource(api_key='test_key'),
        ]

        with patch.object(ConfigManager, '_validate_api_key'):
            manager = ConfigManager(sources)

            # Test getting value with source
            config_value = manager.get_value_with_source('api_key')
            assert config_value.value == 'test_key'
            assert config_value.source == 'cli'

    def test_config_manager_get_nonexistent_key(self):
        """Test getting non-existent configuration key"""
        sources = [DefaultConfigSource()]

        with patch.object(ConfigManager, '_validate_api_key'):
            manager = ConfigManager(sources)

            # Test getting non-existent key
            assert manager.get('nonexistent_key') is None
            assert manager.get_value_with_source('nonexistent_key') is None

    def test_config_manager_api_key_validation_success(self):
        """Test successful API key validation"""
        sources = [ArgConfigSource(api_key='valid_key')]

        # Should not raise exception
        manager = ConfigManager(sources)
        assert manager.get('api_key') == 'valid_key'

    def test_config_manager_api_key_validation_failure_no_key(self):
        """Test API key validation failure when no key provided"""
        sources = [DefaultConfigSource()]

        with patch('sys.exit') as mock_exit:
            ConfigManager(sources)
            mock_exit.assert_called_with(1)

    def test_config_manager_api_key_validation_failure_default_source(self):
        """Test API key validation failure when key is from default source"""
        sources = [DefaultConfigSource()]

        with patch('sys.exit') as mock_exit:
            ConfigManager(sources)
            mock_exit.assert_called_with(1)

    def test_config_manager_setup_basic(self):
        """Test basic setup method"""
        with patch.object(FileConfigSource, 'get_config_path') as mock_get_path:
            mock_path = Path('/nonexistent/config.json')
            mock_get_path.return_value = mock_path

            manager = ConfigManager.setup(api_key='test_key')

            # Verify source order and types
            assert len(manager.sources) == 4  # Default, File, Env, Arg
            assert isinstance(manager.sources[0], DefaultConfigSource)
            assert isinstance(manager.sources[1], FileConfigSource)
            assert isinstance(manager.sources[2], EnvConfigSource)
            assert isinstance(manager.sources[3], ArgConfigSource)

            assert manager.get('api_key') == 'test_key'

    def test_config_manager_setup_with_config_file(self):
        """Test setup method with config file"""
        config_data = {'model_name': 'file_model'}

        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(config_data, f)
            config_file_path = f.name

        try:
            with patch.object(FileConfigSource, 'get_config_path') as mock_get_path:
                mock_path = Path('/nonexistent/config.json')
                mock_get_path.return_value = mock_path

                manager = ConfigManager.setup(api_key='test_key', config_file=config_file_path)

                # Should have file config source instead of global
                assert len(manager.sources) == 4  # Default, Env, File, Arg
                assert isinstance(manager.sources[2], FileConfigSource)
                assert manager.sources[2].config_file == config_file_path

                assert manager.get('model_name') == 'file_model'
                assert manager.get('api_key') == 'test_key'
        finally:
            os.unlink(config_file_path)

    def test_config_manager_setup_all_parameters(self):
        """Test setup method with all parameters"""
        with patch.object(FileConfigSource, 'get_config_path') as mock_get_path:
            mock_path = Path('/nonexistent/config.json')
            mock_get_path.return_value = mock_path

            manager = ConfigManager.setup(
                api_key='test_key',
                model_name='test_model',
                base_url='https://test.com',
                model_azure=True,
                max_tokens=1000,
                context_window_threshold=50000,
                extra_header='{"test": "header"}',
                extra_body='{"test": "body"}',
                enable_thinking=True,
                api_version='test-version',
                theme='light',
            )

            # All CLI arguments should override other sources
            assert manager.get('api_key') == 'test_key'
            assert manager.get('model_name') == 'test_model'
            assert manager.get('base_url') == 'https://test.com'
            assert manager.get('model_azure') is True
            assert manager.get('max_tokens') == 1000
            assert manager.get('context_window_threshold') == 50000
            assert manager.get('enable_thinking') is True
            assert manager.get('api_version') == 'test-version'
            assert manager.get('theme') == 'light'

    def test_config_manager_rich_representation(self):
        """Test ConfigManager rich representation"""
        sources = [ArgConfigSource(api_key='test_key')]

        manager = ConfigManager(sources)
        rich_repr = manager.__rich__()

        # Should return a Group object
        assert hasattr(rich_repr, 'renderables')

    @patch.dict(os.environ, {'API_KEY': 'env_key'})
    def test_config_manager_complex_merge(self):
        """Test complex configuration merge scenario"""
        config_data = {'model_name': 'file_model', 'max_tokens': 4000}

        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(config_data, f)
            config_file_path = f.name

        try:
            with patch.object(FileConfigSource, 'get_config_path') as mock_get_path:
                mock_path = Path('/nonexistent/config.json')
                mock_get_path.return_value = mock_path

                manager = ConfigManager.setup(
                    model_name='cli_model',  # Should override file
                    config_file=config_file_path,
                )

                # Priority: CLI > Env > File > Default
                assert manager.get('api_key') == 'env_key'  # From environment
                assert manager.get('model_name') == 'cli_model'  # From CLI (highest priority)
                assert manager.get('max_tokens') == 4000  # From file

                # Verify sources
                api_key_source = manager.get_value_with_source('api_key')
                model_name_source = manager.get_value_with_source('model_name')
                max_tokens_source = manager.get_value_with_source('max_tokens')

                assert api_key_source.source == 'env'
                assert model_name_source.source == 'cli'
                assert max_tokens_source.source == Path(config_file_path).name  # File source name is filename for custom paths
        finally:
            os.unlink(config_file_path)

    def test_config_manager_setup_nonexistent_config_file(self):
        """Test setup method with non-existent config file should raise ValueError"""
        import pytest

        nonexistent_config = '/nonexistent/path/config.json'

        # Should raise ValueError when config file doesn't exist
        with pytest.raises(ValueError, match='Configuration file not found'):
            ConfigManager.setup(api_key='test_key', config_file=nonexistent_config)

    def test_config_manager_setup_nonexistent_named_config(self):
        """Test setup method with non-existent named config should raise ValueError"""
        import pytest

        # Should raise ValueError when named config doesn't exist
        with pytest.raises(ValueError, match='Configuration file not found'):
            ConfigManager.setup(api_key='test_key', config_file='nonexistent_config_name')
