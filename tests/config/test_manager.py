import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from klaudecode.config.arg_source import ArgConfigSource
from klaudecode.config.default_source import DefaultConfigSource
from klaudecode.config.env_source import EnvConfigSource
from klaudecode.config.file_arg_source import FileConfigSource
from klaudecode.config.global_source import GlobalConfigSource
from klaudecode.config.manager import ConfigManager


class TestConfigManager:
    """测试 ConfigManager 类"""

    def test_config_manager_initialization(self):
        """测试 ConfigManager 基本初始化"""
        sources = [DefaultConfigSource()]

        with patch.object(ConfigManager, '_validate_api_key'):
            manager = ConfigManager(sources)
            assert manager.sources == sources
            assert manager._merged_config_model is not None

    def test_config_manager_merge_priority(self):
        """测试配置合并优先级"""
        # 创建多个配置源，后面的优先级更高
        sources = [
            DefaultConfigSource(),  # model_name: claude-sonnet-4-20250514
            ArgConfigSource(model_name='cli_model', api_key='test_key'),  # model_name: cli_model
        ]

        with patch.object(ConfigManager, '_validate_api_key'):
            manager = ConfigManager(sources)

            # CLI 参数应该覆盖默认值
            assert manager.get('model_name') == 'cli_model'
            assert manager.get('api_key') == 'test_key'

    def test_config_manager_get_value_with_source(self):
        """测试获取带源信息的配置值"""
        sources = [ArgConfigSource(api_key='test_key')]

        with patch.object(ConfigManager, '_validate_api_key'):
            manager = ConfigManager(sources)

            config_value = manager.get_value_with_source('api_key')
            assert config_value.value == 'test_key'
            assert config_value.source == 'cli'

    def test_config_manager_get_nonexistent_key(self):
        """测试获取不存在的配置键"""
        sources = [DefaultConfigSource()]

        with patch.object(ConfigManager, '_validate_api_key'):
            manager = ConfigManager(sources)

            assert manager.get('nonexistent_key') is None
            assert manager.get_value_with_source('nonexistent_key') is None

    def test_config_manager_api_key_validation_success(self):
        """测试 API 密钥验证成功"""
        sources = [ArgConfigSource(api_key='valid_key')]

        # 不应该抛出异常
        manager = ConfigManager(sources)
        assert manager.get('api_key') == 'valid_key'

    def test_config_manager_api_key_validation_failure_no_key(self):
        """测试 API 密钥验证失败 - 没有密钥"""
        sources = [DefaultConfigSource()]  # 默认源没有 API 密钥

        with patch('klaudecode.config.manager.console') as mock_console:
            with patch('sys.exit') as mock_exit:
                ConfigManager(sources)
                mock_console.print.assert_called()
                mock_exit.assert_called_with(1)

    def test_config_manager_api_key_validation_failure_default_source(self):
        """测试 API 密钥验证失败 - 来自默认源"""
        from klaudecode.config.model import ConfigValue

        # 创建一个假的默认源，带有 API 密钥但标记为 'default'
        default_source = DefaultConfigSource()
        # 手动设置 API 密钥但保持 'default' 源标记
        default_source.config_model.api_key = ConfigValue(value='default_key', source='default')

        sources = [default_source]

        with patch('klaudecode.config.manager.console') as mock_console:
            with patch('sys.exit') as mock_exit:
                ConfigManager(sources)
                mock_console.print.assert_called()
                mock_exit.assert_called_with(1)

    def test_config_manager_setup_basic(self):
        """测试基本 setup 方法"""
        with patch.object(GlobalConfigSource, 'get_config_path') as mock_get_path:
            mock_path = Path('/nonexistent/config.json')
            mock_get_path.return_value = mock_path

            manager = ConfigManager.setup(api_key='test_key')

            # 验证源的顺序和类型
            assert len(manager.sources) == 4  # Default, Global, Env, Arg
            assert isinstance(manager.sources[0], DefaultConfigSource)
            assert isinstance(manager.sources[1], GlobalConfigSource)
            assert isinstance(manager.sources[2], EnvConfigSource)
            assert isinstance(manager.sources[3], ArgConfigSource)

            assert manager.get('api_key') == 'test_key'

    def test_config_manager_setup_with_config_file(self):
        """测试带配置文件的 setup 方法"""
        config_data = {'model_name': 'file_model'}

        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(config_data, f)
            config_file_path = f.name

        try:
            with patch.object(GlobalConfigSource, 'get_config_path') as mock_get_path:
                mock_path = Path('/nonexistent/config.json')
                mock_get_path.return_value = mock_path

                manager = ConfigManager.setup(api_key='test_key', config_file=config_file_path)

                # 验证源的顺序和类型
                assert len(manager.sources) == 5  # Default, Global, Env, File, Arg
                assert isinstance(manager.sources[0], DefaultConfigSource)
                assert isinstance(manager.sources[1], GlobalConfigSource)
                assert isinstance(manager.sources[2], EnvConfigSource)
                assert isinstance(manager.sources[3], FileConfigSource)
                assert isinstance(manager.sources[4], ArgConfigSource)

                assert manager.get('api_key') == 'test_key'
                assert manager.get('model_name') == 'file_model'  # 来自文件
        finally:
            Path(config_file_path).unlink()

    def test_config_manager_setup_all_parameters(self):
        """测试带所有参数的 setup 方法"""
        with patch.object(GlobalConfigSource, 'get_config_path') as mock_get_path:
            mock_path = Path('/nonexistent/config.json')
            mock_get_path.return_value = mock_path

            manager = ConfigManager.setup(
                api_key='test_key',
                model_name='test_model',
                base_url='https://test.example.com',
                model_azure=True,
                max_tokens=3000,
                context_window_threshold=150000,
                extra_header='{"Authorization": "Bearer token"}',
                extra_body='{"custom": "value"}',
                enable_thinking=True,
                api_version='2024-05-01',
                theme='light',
            )

            assert manager.get('api_key') == 'test_key'
            assert manager.get('model_name') == 'test_model'
            assert manager.get('base_url') == 'https://test.example.com'
            assert manager.get('model_azure') is True
            assert manager.get('max_tokens') == 3000
            assert manager.get('context_window_threshold') == 150000
            assert manager.get('extra_header') == {'Authorization': 'Bearer token'}
            assert manager.get('extra_body') == {'custom': 'value'}
            assert manager.get('enable_thinking') is True
            assert manager.get('api_version') == '2024-05-01'
            assert manager.get('theme') == 'light'

    def test_config_manager_rich_representation(self):
        """测试 rich 表示"""
        sources = [ArgConfigSource(api_key='test_key')]

        with patch.object(ConfigManager, '_validate_api_key'):
            manager = ConfigManager(sources)

            rich_output = manager.__rich__()
            assert rich_output is not None

    @patch.dict(os.environ, {'API_KEY': 'env_key'})
    def test_config_manager_complex_merge(self):
        """测试复杂的配置合并场景"""
        config_data = {'model_name': 'file_model', 'max_tokens': 4000}

        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(config_data, f)
            config_file_path = f.name

        try:
            with patch.object(GlobalConfigSource, 'get_config_path') as mock_get_path:
                mock_path = Path('/nonexistent/config.json')
                mock_get_path.return_value = mock_path

                # 优先级：Default < Global < Env < File < CLI
                manager = ConfigManager.setup(
                    api_key='cli_key',  # CLI: 最高优先级
                    model_name='cli_model',  # CLI: 覆盖文件配置
                    config_file=config_file_path,  # File: 覆盖环境变量
                    # max_tokens 来自文件 (4000)
                    # API_KEY 环境变量被 CLI 参数覆盖
                )

                assert manager.get('api_key') == 'cli_key'  # CLI 优先
                assert manager.get('model_name') == 'cli_model'  # CLI 优先
                assert manager.get('max_tokens') == 4000  # 来自文件

                # 验证源信息
                api_key_source = manager.get_value_with_source('api_key')
                model_name_source = manager.get_value_with_source('model_name')
                max_tokens_source = manager.get_value_with_source('max_tokens')

                assert api_key_source.source == 'cli'
                assert model_name_source.source == 'cli'
                assert max_tokens_source.source == '--config'
        finally:
            Path(config_file_path).unlink()
