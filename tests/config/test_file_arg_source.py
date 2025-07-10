import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from klaudecode.config.file_arg_source import FileArgConfigSource


class TestFileConfigSource:
    """测试 FileConfigSource 类"""

    def test_file_config_source_with_valid_file(self):
        """测试有效配置文件的加载"""
        config_data = {'api_key': 'file_api_key', 'model_name': 'file_model', 'max_tokens': 3000}

        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(config_data, f)
            config_path = f.name

        try:
            source = FileArgConfigSource(config_path)
            assert source.source == '--config'
            assert source.config_file == config_path
            assert source.get('api_key') == 'file_api_key'
            assert source.get('model_name') == 'file_model'
            assert source.get('max_tokens') == 3000
        finally:
            Path(config_path).unlink()

    def test_file_config_source_with_nonexistent_file(self):
        """测试不存在的配置文件"""
        nonexistent_path = '/nonexistent/path/config.json'

        with patch('klaudecode.config.file_arg_source.console') as mock_console:
            source = FileArgConfigSource(nonexistent_path)
            assert source.source == '--config'
            assert source.config_file == nonexistent_path
            assert source.config_model is not None

            # 应该打印警告信息
            mock_console.print.assert_called_once()
            warning_call = mock_console.print.call_args[0][0]
            assert 'Config file not found' in str(warning_call)

    def test_file_config_source_with_invalid_json(self):
        """测试无效 JSON 文件"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            f.write('invalid json content')
            config_path = f.name

        try:
            with patch('klaudecode.config.file_arg_source.console') as mock_console:
                source = FileArgConfigSource(config_path)
                assert source.source == '--config'
                assert source.config_model is not None

                # 应该打印警告信息
                mock_console.print.assert_called_once()
                warning_call = mock_console.print.call_args[0][0]
                assert 'Failed to load config file' in str(warning_call)
        finally:
            Path(config_path).unlink()

    def test_file_config_source_filters_invalid_fields(self):
        """测试过滤无效字段"""
        config_data = {'api_key': 'test_key', 'model_name': 'test_model', 'invalid_field': 'should_be_ignored', 'another_invalid': 123}

        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(config_data, f)
            config_path = f.name

        try:
            source = FileArgConfigSource(config_path)
            assert source.get('api_key') == 'test_key'
            assert source.get('model_name') == 'test_model'
            assert source.get('invalid_field') is None
            assert source.get('another_invalid') is None
        finally:
            Path(config_path).unlink()

    def test_file_config_source_with_all_fields(self):
        """测试包含所有有效字段的配置文件"""
        config_data = {
            'api_key': 'test_key',
            'model_name': 'test_model',
            'base_url': 'https://test.example.com',
            'model_azure': True,
            'max_tokens': 4000,
            'context_window_threshold': 180000,
            'extra_header': {'Authorization': 'Bearer token'},
            'extra_body': {'custom': 'value'},
            'enable_thinking': True,
            'api_version': '2024-05-01',
            'theme': 'light',
        }

        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(config_data, f)
            config_path = f.name

        try:
            source = FileArgConfigSource(config_path)
            assert source.get('api_key') == 'test_key'
            assert source.get('model_name') == 'test_model'
            assert source.get('base_url') == 'https://test.example.com'
            assert source.get('model_azure') is True
            assert source.get('max_tokens') == 4000
            assert source.get('context_window_threshold') == 180000
            assert source.get('extra_header') == {'Authorization': 'Bearer token'}
            assert source.get('extra_body') == {'custom': 'value'}
            assert source.get('enable_thinking') is True
            assert source.get('api_version') == '2024-05-01'
            assert source.get('theme') == 'light'
        finally:
            Path(config_path).unlink()

    def test_file_config_source_config_value_properties(self):
        """测试配置值的属性"""
        config_data = {'api_key': 'test_key'}

        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(config_data, f)
            config_path = f.name

        try:
            source = FileArgConfigSource(config_path)
            config_value = source.config_model.api_key
            assert config_value.value == 'test_key'
            assert config_value.source == '--config'
        finally:
            Path(config_path).unlink()

    def test_file_config_source_empty_file(self):
        """测试空的配置文件"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump({}, f)
            config_path = f.name

        try:
            source = FileArgConfigSource(config_path)
            assert source.config_model is not None
            assert source.get('api_key') is None
            assert source.get('model_name') is None
        finally:
            Path(config_path).unlink()
