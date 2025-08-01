from unittest.mock import patch

from klaudecode.config.model import ConfigModel, ConfigValue, parse_json_string


class TestConfigValue:
    """Test ConfigValue data class"""

    def test_config_value_initialization(self):
        """Test ConfigValue initialization"""
        config_value = ConfigValue(value="test", source="cli")
        assert config_value.value == "test"
        assert config_value.source == "cli"

    def test_config_value_bool_true(self):
        """Test ConfigValue boolean value - True"""
        config_value = ConfigValue(value="test", source="cli")
        assert bool(config_value) is True

    def test_config_value_bool_false(self):
        """Test ConfigValue boolean value - False"""
        config_value = ConfigValue(value=None, source="cli")
        assert bool(config_value) is False

    def test_config_value_bool_empty_string(self):
        """Test ConfigValue boolean value - empty string"""
        config_value = ConfigValue(value="", source="cli")
        assert bool(config_value) is True  # Empty string is not None, so it's True


class TestParseJsonString:
    """Test parse_json_string function"""

    def test_parse_valid_json_string(self):
        """Test parsing valid JSON string"""
        json_str = '{"key": "value", "number": 123}'
        result = parse_json_string(json_str)
        assert result == {"key": "value", "number": 123}

    def test_parse_dict_passthrough(self):
        """Test dict is returned directly"""
        input_dict = {"key": "value"}
        result = parse_json_string(input_dict)
        assert result == input_dict

    @patch("klaudecode.tui.console")
    def test_parse_invalid_json_string(self, mock_console):
        """Test parsing invalid JSON string"""
        invalid_json = "{'invalid': json}"
        result = parse_json_string(invalid_json)
        assert result == {}
        mock_console.print.assert_called_once()

    def test_parse_non_string_non_dict(self):
        """Test handling non-string non-dict input"""
        result = parse_json_string(123)
        assert result == {}

    def test_parse_empty_string(self):
        """Test parsing empty string"""
        result = parse_json_string("")
        assert result == {}


class TestConfigModel:
    """Test ConfigModel class"""

    def test_config_model_initialization(self):
        """Test ConfigModel initialization"""
        model = ConfigModel(source="test")
        assert model.api_key is None
        assert model.model_name is None

    def test_config_model_with_values(self):
        """Test ConfigModel initialization with values"""
        model = ConfigModel(
            source="test", api_key="test_key", model_name="test_model", max_tokens=1000
        )

        assert model.api_key.value == "test_key"
        assert model.api_key.source == "test"
        assert model.model_name.value == "test_model"
        assert model.max_tokens.value == 1000

    def test_config_model_none_values_ignored(self):
        """Test None values are ignored"""
        model = ConfigModel(source="test", api_key="test_key", model_name=None)

        assert model.api_key.value == "test_key"
        assert model.model_name is None

    def test_config_model_model_validate(self):
        """Test model_validate method"""
        data = {
            "api_key": {"value": "test_key", "source": "env"},
            "model_name": {"value": "test_model", "source": "cli"},
        }

        model = ConfigModel.model_validate(data)
        assert model.api_key.value == "test_key"
        assert model.api_key.source == "env"
        assert model.model_name.value == "test_model"
        assert model.model_name.source == "cli"

    def test_config_model_model_validate_mixed_data(self):
        """Test model_validate handling mixed data"""
        data = {
            "api_key": {"value": "test_key", "source": "env"},
            "model_name": {"value": "direct_value", "source": "test"},
        }

        model = ConfigModel.model_validate(data)
        assert model.api_key.value == "test_key"
        assert model.api_key.source == "env"
        assert model.model_name.value == "direct_value"
        assert model.model_name.source == "test"

    def test_config_model_rich_representation(self):
        """Test rich representation"""
        model = ConfigModel(source="test", api_key="test_key", model_name="test_model")

        rich_output = model.__rich__()
        assert rich_output is not None
