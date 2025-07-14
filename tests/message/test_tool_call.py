import json
from unittest.mock import patch

from klaudecode.message.tool_call import ToolCall


class TestToolCall:
    def test_tool_call_basic_initialization(self):
        tool_call = ToolCall(id='call_123', tool_name='test_tool', tool_args_dict={'param1': 'value1', 'param2': 42})

        assert tool_call.id == 'call_123'
        assert tool_call.tool_name == 'test_tool'
        assert tool_call.tool_args_dict == {'param1': 'value1', 'param2': 42}
        assert tool_call.status == 'processing'

    def test_tool_call_with_status(self):
        tool_call = ToolCall(id='call_456', tool_name='test_tool', status='success')

        assert tool_call.status == 'success'

    def test_tool_args_property(self):
        tool_call = ToolCall(id='call_123', tool_name='test_tool', tool_args_dict={'param': 'value', 'number': 123})

        tool_args = tool_call.tool_args
        parsed_args = json.loads(tool_args)

        assert parsed_args == {'param': 'value', 'number': 123}

    def test_tool_args_property_empty_dict(self):
        tool_call = ToolCall(id='call_123', tool_name='test_tool', tool_args_dict={})

        assert tool_call.tool_args == '{}'

    def test_initialization_with_tool_args_string(self):
        tool_args_str = '{"param": "value", "number": 123}'
        tool_call = ToolCall(id='call_123', tool_name='test_tool', tool_args=tool_args_str)

        assert tool_call.tool_args_dict == {'param': 'value', 'number': 123}
        assert tool_call.tool_args == tool_args_str

    def test_initialization_with_invalid_tool_args_string(self):
        invalid_json = '{"param": invalid json}'
        tool_call = ToolCall(id='call_123', tool_name='test_tool', tool_args=invalid_json)

        assert tool_call.tool_args_dict == {}
        assert tool_call.tool_args == '{}'

    def test_initialization_with_empty_tool_args_string(self):
        tool_call = ToolCall(id='call_123', tool_name='test_tool', tool_args='')

        assert tool_call.tool_args_dict == {}
        assert tool_call.tool_args == '{}'

    def test_initialization_tool_args_dict_takes_precedence(self):
        tool_call = ToolCall(id='call_123', tool_name='test_tool', tool_args='{"should": "be_ignored"}', tool_args_dict={'actual': 'value'})

        assert tool_call.tool_args_dict == {'actual': 'value'}

    @patch('klaudecode.message.tool_call.count_tokens')
    def test_tokens_property(self, mock_count_tokens):
        mock_count_tokens.side_effect = [5, 10]  # First call for tool_name, second for tool_args

        tool_call = ToolCall(id='call_123', tool_name='test_tool', tool_args_dict={'param': 'value'})

        tokens = tool_call.tokens

        assert tokens == 15
        assert mock_count_tokens.call_count == 2
        mock_count_tokens.assert_any_call('test_tool')
        mock_count_tokens.assert_any_call(tool_call.tool_args)

    def test_to_openai(self):
        tool_call = ToolCall(id='call_123', tool_name='test_tool', tool_args_dict={'param': 'value'})

        result = tool_call.to_openai()

        assert result['id'] == 'call_123'
        assert result['type'] == 'function'
        assert result['function']['name'] == 'test_tool'
        assert result['function']['arguments'] == tool_call.tool_args

    def test_to_anthropic(self):
        tool_call = ToolCall(id='call_123', tool_name='test_tool', tool_args_dict={'param': 'value', 'number': 42})

        result = tool_call.to_anthropic()

        assert result['id'] == 'call_123'
        assert result['type'] == 'tool_use'
        assert result['name'] == 'test_tool'
        assert result['input'] == {'param': 'value', 'number': 42}

    def test_get_display_tool_name_regular(self):
        display_name = ToolCall.get_display_tool_name('regular_tool')

        assert display_name == 'regular_tool'

    def test_get_display_tool_name_mcp(self):
        display_name = ToolCall.get_display_tool_name('mcp__special_tool')

        assert display_name == 'special_tool(MCP)'

    def test_get_display_tool_args(self):
        args_dict = {'param1': 'value1', 'param2': 42, 'param3': True}

        result = ToolCall.get_display_tool_args(args_dict)

        # The result is a Rich Text object, so we check the plain text
        result_text = result.plain
        assert 'param1=value1' in result_text
        assert 'param2=42' in result_text
        assert 'param3=True' in result_text

    def test_get_display_tool_args_empty(self):
        result = ToolCall.get_display_tool_args({})

        assert result.plain == ''

    @patch('klaudecode.message.registry._TOOL_CALL_RENDERERS', {})
    def test_rich_console_no_custom_renderer(self):
        tool_call = ToolCall(id='call_123', tool_name='test_tool', tool_args_dict={'param': 'value'}, status='success')

        # Mock console and options
        console = None
        options = None

        result = list(tool_call.__rich_console__(console, options))

        # Should yield one rendered message
        assert len(result) == 1

    @patch('klaudecode.message.registry._TOOL_CALL_RENDERERS')
    def test_rich_console_with_custom_renderer(self, mock_renderers):
        def mock_renderer(tc):
            return ['Custom rendered tool call']

        mock_renderers.__getitem__.return_value = mock_renderer
        mock_renderers.__contains__.return_value = True

        tool_call = ToolCall(id='call_123', tool_name='test_tool', tool_args_dict={'param': 'value'})

        result = list(tool_call.__rich_console__(None, None))

        # Should yield the custom rendered output
        assert len(result) >= 1

    @patch('klaudecode.message.registry._TOOL_CALL_RENDERERS', {})
    def test_get_suffix_renderable_no_custom_renderer(self):
        tool_call = ToolCall(id='call_123', tool_name='test_tool', tool_args_dict={'param': 'value'})

        result = list(tool_call.get_suffix_renderable())

        # Should yield one suffix display
        assert len(result) == 1

    @patch('klaudecode.message.registry._TOOL_CALL_RENDERERS')
    def test_get_suffix_renderable_with_custom_renderer(self, mock_renderers):
        def mock_renderer(tc, is_suffix=False):
            return ['Custom suffix'] if is_suffix else ['Normal']

        mock_renderers.__getitem__.return_value = mock_renderer
        mock_renderers.__contains__.return_value = True

        tool_call = ToolCall(id='call_123', tool_name='test_tool', tool_args_dict={'param': 'value'})

        result = list(tool_call.get_suffix_renderable())

        # Should use custom renderer with is_suffix=True
        assert len(result) >= 1
