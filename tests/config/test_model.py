from unittest.mock import patch

from klaudecode.config.model import ConfigModel, ConfigValue, parse_json_string


class TestConfigValue:
    """测试 ConfigValue 数据类"""

    def test_config_value_initialization(self):
        """测试 ConfigValue 初始化"""
        config_value = ConfigValue(value='test', source='cli')
        assert config_value.value == 'test'
        assert config_value.source == 'cli'

    def test_config_value_bool_true(self):
        """测试 ConfigValue 布尔值 - True"""
        config_value = ConfigValue(value='test', source='cli')
        assert bool(config_value) is True

    def test_config_value_bool_false(self):
        """测试 ConfigValue 布尔值 - False"""
        config_value = ConfigValue(value=None, source='cli')
        assert bool(config_value) is False

    def test_config_value_bool_empty_string(self):
        """测试 ConfigValue 布尔值 - 空字符串"""
        config_value = ConfigValue(value='', source='cli')
        assert bool(config_value) is True  # 空字符串不是 None，所以是 True


class TestParseJsonString:
    """测试 parse_json_string 函数"""

    def test_parse_valid_json_string(self):
        """测试解析有效的 JSON 字符串"""
        json_str = '{"key": "value", "number": 123}'
        result = parse_json_string(json_str)
        assert result == {'key': 'value', 'number': 123}

    def test_parse_dict_passthrough(self):
        """测试字典直接返回"""
        input_dict = {'key': 'value'}
        result = parse_json_string(input_dict)
        assert result == input_dict

    @patch('klaudecode.tui.console')
    def test_parse_invalid_json_string(self, mock_console):
        """测试解析无效的 JSON 字符串"""
        invalid_json = "{'invalid': json}"
        result = parse_json_string(invalid_json)
        assert result == {}
        mock_console.print.assert_called_once()

    def test_parse_non_string_non_dict(self):
        """测试处理非字符串非字典输入"""
        result = parse_json_string(123)
        assert result == {}

    def test_parse_empty_string(self):
        """测试解析空字符串"""
        result = parse_json_string('')
        assert result == {}


class TestConfigModel:
    """测试 ConfigModel 类"""

    def test_config_model_initialization(self):
        """测试 ConfigModel 初始化"""
        model = ConfigModel(source='test')
        assert model.api_key is None
        assert model.model_name is None

    def test_config_model_with_values(self):
        """测试带值的 ConfigModel 初始化"""
        model = ConfigModel(source='test', api_key='test_key', model_name='test_model', max_tokens=1000)

        assert model.api_key.value == 'test_key'
        assert model.api_key.source == 'test'
        assert model.model_name.value == 'test_model'
        assert model.max_tokens.value == 1000

    def test_config_model_none_values_ignored(self):
        """测试 None 值被忽略"""
        model = ConfigModel(source='test', api_key='test_key', model_name=None)

        assert model.api_key.value == 'test_key'
        assert model.model_name is None

    def test_config_model_model_validate(self):
        """测试 model_validate 方法"""
        data = {'api_key': {'value': 'test_key', 'source': 'env'}, 'model_name': {'value': 'test_model', 'source': 'cli'}}

        model = ConfigModel.model_validate(data)
        assert model.api_key.value == 'test_key'
        assert model.api_key.source == 'env'
        assert model.model_name.value == 'test_model'
        assert model.model_name.source == 'cli'

    def test_config_model_model_validate_mixed_data(self):
        """测试 model_validate 处理混合数据"""
        data = {'api_key': {'value': 'test_key', 'source': 'env'}, 'model_name': {'value': 'direct_value', 'source': 'test'}}

        model = ConfigModel.model_validate(data)
        assert model.api_key.value == 'test_key'
        assert model.api_key.source == 'env'
        assert model.model_name.value == 'direct_value'
        assert model.model_name.source == 'test'

    def test_config_model_rich_representation(self):
        """测试 rich 表示"""
        model = ConfigModel(source='test', api_key='test_key', model_name='test_model')

        rich_output = model.__rich__()
        assert rich_output is not None
