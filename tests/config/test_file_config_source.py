import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from klaudecode.config.file_config_source import (
    FileConfigSource,
    get_default_config_path,
    resolve_config_path,
)


class TestFileConfigSource:
    """Test FileConfigSource class"""

    def test_file_config_source_initialization_default(self):
        """Test FileConfigSource initialization with default config"""
        with patch("pathlib.Path.exists", return_value=False):
            source = FileConfigSource()

            assert source.config_file is None
            assert source.config_path == get_default_config_path()
            assert source.source == "global"
            assert source.config_model is not None

    def test_file_config_source_initialization_with_file(self):
        """Test FileConfigSource initialization with specific config file"""
        with patch("pathlib.Path.exists", return_value=False):
            source = FileConfigSource("anthropic")

            assert source.config_file == "anthropic"
            assert (
                source.config_path == Path.home() / ".klaude" / "config_anthropic.json"
            )
            assert source.source == "anthropic"
            assert source.config_model is not None

    def test_file_config_source_load_existing_file(self):
        """Test loading existing configuration file"""
        config_data = {
            "api_key": "test_key",
            "model_name": "test_model",
            "max_tokens": 1000,
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(config_data, f)
            config_file_path = f.name

        try:
            source = FileConfigSource(config_file_path)

            assert source.config_model.api_key.value == "test_key"
            assert source.config_model.model_name.value == "test_model"
            assert source.config_model.max_tokens.value == 1000

            # All values should come from the file source (source name is filename for custom paths)
            expected_source_name = Path(config_file_path).name
            assert source.config_model.api_key.source == expected_source_name
            assert source.config_model.model_name.source == expected_source_name
            assert source.config_model.max_tokens.source == expected_source_name
        finally:
            Path(config_file_path).unlink()

    def test_file_config_source_invalid_json(self):
        """Test handling of invalid JSON file"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("invalid json content")
            config_file_path = f.name

        try:
            with patch(
                "klaudecode.tui.console.print"
            ):  # Mock console to suppress error output
                source = FileConfigSource(config_file_path)

                # Should create empty config model when JSON is invalid
                assert source.config_model is not None
                assert source.config_model.api_key is None
        finally:
            Path(config_file_path).unlink()

    def test_file_config_source_nonexistent_file_default(self):
        """Test handling of non-existent default config file"""
        with patch("pathlib.Path.exists", return_value=False):
            source = FileConfigSource()  # Default config, should not raise

            # Should create empty config model when default file doesn't exist
            assert source.config_model is not None
            assert source.config_model.api_key is None

    def test_file_config_source_nonexistent_file_cli_specified(self):
        """Test handling of non-existent CLI-specified config file"""
        nonexistent_path = "/nonexistent/path/config.json"

        # Direct constructor should not raise, just create empty config
        source = FileConfigSource(nonexistent_path)
        assert source.config_model is not None
        assert source.config_model.api_key is None

    def test_file_config_source_filter_invalid_fields(self):
        """Test filtering of invalid configuration fields"""
        config_data = {
            "api_key": "test_key",
            "model_name": "test_model",
            "invalid_field": "should_be_ignored",
            "another_invalid": 123,
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(config_data, f)
            config_file_path = f.name

        try:
            source = FileConfigSource(config_file_path)

            # Valid fields should be loaded
            assert source.config_model.api_key.value == "test_key"
            assert source.config_model.model_name.value == "test_model"

            # Invalid fields should not cause errors (they're filtered out)
            assert not hasattr(source.config_model, "invalid_field")
            assert not hasattr(source.config_model, "another_invalid")
        finally:
            Path(config_file_path).unlink()

    def test_determine_source_name_global(self):
        """Test source name determination for global config"""
        with patch("pathlib.Path.exists", return_value=False):
            source = FileConfigSource()
            assert source.source == "global"

    def test_determine_source_name_named_config(self):
        """Test source name determination for named config files"""
        with patch("pathlib.Path.exists", return_value=False):
            source = FileConfigSource("anthropic")
            assert source.source == "anthropic"

            source = FileConfigSource("openai")
            assert source.source == "openai"

    def test_determine_source_name_custom_path(self):
        """Test source name determination for custom path"""
        with patch("pathlib.Path.exists", return_value=False):
            source = FileConfigSource("/tmp/custom.json")
            assert source.source == "custom.json"

            source = FileConfigSource("/some/path/config.json")
            assert source.source == "config.json"

    def test_determine_source_name_manual_override(self):
        """Test manual source name override"""
        with patch("pathlib.Path.exists", return_value=False):
            source = FileConfigSource("anthropic", source_name="manual_name")
            assert source.source == "manual_name"

    def test_create_global_config_source(self):
        """Test global config source factory method"""
        with patch("pathlib.Path.exists", return_value=False):
            source = FileConfigSource.create_global_config_source()

            assert source.config_file is None
            assert source.source == "global"
            assert source.config_path == get_default_config_path()

    def test_create_cli_config_source(self):
        """Test CLI config source factory method"""
        import pytest

        # Should raise ValueError when CLI config file doesn't exist
        with pytest.raises(ValueError, match="Configuration file not found"):
            FileConfigSource.create_cli_config_source(
                "definitely_nonexistent_config_12345"
            )

    def test_get_config_path_class_method(self):
        """Test get_config_path class method"""
        path = FileConfigSource.get_config_path()
        assert path == get_default_config_path()
        assert path == Path.home() / ".klaude" / "config.json"

    def test_create_example_config(self):
        """Test creating example configuration file"""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "test_config.json"

            with patch("klaudecode.tui.console.print"):  # Mock console output
                result = FileConfigSource.create_example_config(config_path)

                assert result is True
                assert config_path.exists()

                # Verify content
                with open(config_path, "r") as f:
                    config_data = json.load(f)

                assert "api_key" in config_data
                assert "model_name" in config_data
                assert "base_url" in config_data
                assert config_data["api_key"] == "your_api_key_here"

    def test_create_example_config_default_path(self):
        """Test creating example config with default path"""
        with (
            patch("pathlib.Path.mkdir"),
            patch("builtins.open", create=True),
            patch("json.dump"),
            patch("klaudecode.tui.console.print"),
        ):
            result = FileConfigSource.create_example_config()
            assert result is True


class TestResolveConfigPath:
    """Test resolve_config_path function"""

    def test_resolve_config_path_absolute(self):
        """Test resolving absolute path"""
        absolute_path = "/absolute/path/to/config.json"
        result = resolve_config_path(absolute_path)
        assert result == Path(absolute_path)

    def test_resolve_config_path_relative_with_separator(self):
        """Test resolving relative path with directory separator"""
        relative_path = "path/to/config.json"
        result = resolve_config_path(relative_path)
        assert result == Path(relative_path)

    def test_resolve_config_path_short_name(self):
        """Test resolving short config name"""
        result = resolve_config_path("anthropic")
        expected = Path.home() / ".klaude" / "config_anthropic.json"
        assert result == expected

    def test_resolve_config_path_with_json_extension(self):
        """Test resolving filename with .json extension"""
        result = resolve_config_path("myconfig.json")
        expected = Path.home() / ".klaude" / "myconfig.json"
        assert result == expected

    def test_resolve_config_path_windows_separator(self):
        """Test resolving path with Windows separator"""
        windows_path = "path\\to\\config.json"
        result = resolve_config_path(windows_path)
        assert result == Path(windows_path)
