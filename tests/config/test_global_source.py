import json
import tempfile
from pathlib import Path
from unittest.mock import patch


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
    GlobalConfigSource,
)


class TestGlobalConfigSource:
    """测试 GlobalConfigSource 类"""

    def test_global_config_source_initialization_no_file(self):
        """测试没有配置文件时的初始化"""
        with patch.object(GlobalConfigSource, 'get_config_path') as mock_get_path:
            mock_path = Path('/nonexistent/config.json')
            mock_get_path.return_value = mock_path

            source = GlobalConfigSource()
            assert source.source == 'config'
            assert source.config_model is not None

    def test_global_config_source_with_valid_file(self):
        """测试有效配置文件的加载"""
        config_data = {'api_key': 'test_key', 'model_name': 'custom_model', 'max_tokens': 4000}

        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(config_data, f)
            config_path = Path(f.name)

        try:
            with patch.object(GlobalConfigSource, 'get_config_path') as mock_get_path:
                mock_get_path.return_value = config_path

                source = GlobalConfigSource()
                assert source.get('api_key') == 'test_key'
                assert source.get('model_name') == 'custom_model'
                assert source.get('max_tokens') == 4000
        finally:
            config_path.unlink()

    def test_global_config_source_with_invalid_json(self):
        """测试无效 JSON 文件的处理"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            f.write('invalid json content')
            config_path = Path(f.name)

        try:
            with patch.object(GlobalConfigSource, 'get_config_path') as mock_get_path:
                mock_get_path.return_value = config_path

                with patch('klaudecode.config.global_source.console') as mock_console:
                    source = GlobalConfigSource()
                    # 应该创建空的配置模型
                    assert source.config_model is not None
                    # 应该打印警告信息
                    mock_console.print.assert_called_once()
        finally:
            config_path.unlink()

    def test_global_config_source_filters_invalid_fields(self):
        """测试过滤无效字段"""
        config_data = {'api_key': 'test_key', 'model_name': 'custom_model', 'invalid_field': 'should_be_ignored', 'another_invalid': 123}

        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(config_data, f)
            config_path = Path(f.name)

        try:
            with patch.object(GlobalConfigSource, 'get_config_path') as mock_get_path:
                mock_get_path.return_value = config_path

                source = GlobalConfigSource()
                assert source.get('api_key') == 'test_key'
                assert source.get('model_name') == 'custom_model'
                assert source.get('invalid_field') is None
                assert source.get('another_invalid') is None
        finally:
            config_path.unlink()

    def test_get_config_path(self):
        """测试获取配置文件路径"""
        config_path = GlobalConfigSource.get_config_path()
        assert config_path == Path.home() / '.klaude' / 'config.json'

    def test_create_example_config(self):
        """测试创建示例配置文件"""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / 'test_config.json'

            with patch('klaudecode.config.global_source.console') as mock_console:
                result = GlobalConfigSource.create_example_config(config_path)
                assert result is True
                assert config_path.exists()

                # 验证配置文件内容
                with open(config_path, 'r', encoding='utf-8') as f:
                    config_data = json.load(f)

                assert config_data['api_key'] == 'your_api_key_here'
                assert config_data['model_name'] == DEFAULT_MODEL_NAME
                assert config_data['base_url'] == DEFAULT_BASE_URL
                assert config_data['model_azure'] == DEFAULT_MODEL_AZURE
                assert config_data['max_tokens'] == DEFAULT_MAX_TOKENS
                assert config_data['context_window_threshold'] == DEFAULT_CONTEXT_WINDOW_THRESHOLD
                assert config_data['extra_header'] == DEFAULT_EXTRA_HEADER
                assert config_data['extra_body'] == DEFAULT_EXTRA_BODY
                assert config_data['enable_thinking'] == DEFAULT_ENABLE_THINKING
                assert config_data['api_version'] == DEFAULT_API_VERSION
                assert config_data['theme'] == DEFAULT_THEME

                mock_console.print.assert_called()

    def test_create_example_config_io_error(self):
        """测试创建示例配置文件时的 IO 错误"""
        # 使用不存在的目录路径，且无法创建
        invalid_path = Path('/invalid/path/that/cannot/be/created/config.json')

        with patch('klaudecode.config.global_source.console') as mock_console:
            result = GlobalConfigSource.create_example_config(invalid_path)
            assert result is False
            mock_console.print.assert_called()

    @patch('os.system')
    @patch('os.getenv')
    def test_open_config_file_exists(self, mock_getenv, mock_system):
        """测试打开存在的配置文件"""
        mock_getenv.return_value = 'test_editor'

        with tempfile.NamedTemporaryFile(delete=False) as f:
            config_path = Path(f.name)

        try:
            with patch.object(GlobalConfigSource, 'get_config_path') as mock_get_path:
                mock_get_path.return_value = config_path

                with patch('klaudecode.config.global_source.console') as mock_console:
                    GlobalConfigSource.open_config_file()
                    mock_system.assert_called_with(f'test_editor {config_path}')
                    mock_console.print.assert_called()
        finally:
            config_path.unlink()

    def test_open_config_file_not_exists(self):
        """测试打开不存在的配置文件"""
        with patch.object(GlobalConfigSource, 'get_config_path') as mock_get_path:
            mock_path = Path('/nonexistent/config.json')
            mock_get_path.return_value = mock_path

            with patch('klaudecode.config.global_source.console') as mock_console:
                GlobalConfigSource.open_config_file()
                mock_console.print.assert_called()

    @patch.object(GlobalConfigSource, 'create_example_config')
    @patch.object(GlobalConfigSource, 'open_config_file')
    def test_edit_config_file_creates_if_not_exists(self, mock_open, mock_create):
        """测试编辑配置文件时，如果不存在则创建"""
        with patch.object(GlobalConfigSource, 'get_config_path') as mock_get_path:
            mock_path = Path('/nonexistent/config.json')
            mock_get_path.return_value = mock_path

            GlobalConfigSource.edit_config_file()
            mock_create.assert_called_once_with(mock_path)
            mock_open.assert_called_once()

    def test_config_value_properties(self):
        """测试配置值的属性"""
        config_data = {'api_key': 'test_key'}

        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(config_data, f)
            config_path = Path(f.name)

        try:
            with patch.object(GlobalConfigSource, 'get_config_path') as mock_get_path:
                mock_get_path.return_value = config_path

                source = GlobalConfigSource()
                config_value = source.config_model.api_key
                assert config_value.value == 'test_key'
                assert config_value.source == 'config'
        finally:
            config_path.unlink()
