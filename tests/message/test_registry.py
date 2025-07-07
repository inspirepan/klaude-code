
from klaudecode.message.registry import (
    register_tool_call_renderer,
    register_tool_result_renderer,
    register_user_msg_content_func,
    register_user_msg_renderer,
    register_user_msg_suffix_renderer,
    _TOOL_CALL_RENDERERS,
    _TOOL_RESULT_RENDERERS,
    _USER_MSG_RENDERERS,
    _USER_MSG_SUFFIX_RENDERERS,
    _USER_MSG_CONTENT_FUNCS,
)


class TestToolCallRenderer:
    def setup_method(self):
        _TOOL_CALL_RENDERERS.clear()

    def teardown_method(self):
        _TOOL_CALL_RENDERERS.clear()

    def test_register_tool_call_renderer(self):
        def mock_renderer(tool_call, is_suffix=False):
            return f'Rendered {tool_call.tool_name}'

        register_tool_call_renderer('test_tool', mock_renderer)

        assert 'test_tool' in _TOOL_CALL_RENDERERS
        assert _TOOL_CALL_RENDERERS['test_tool'] == mock_renderer

    def test_multiple_tool_call_renderers(self):
        def renderer1(tool_call, is_suffix=False):
            return 'renderer1'

        def renderer2(tool_call, is_suffix=False):
            return 'renderer2'

        register_tool_call_renderer('tool1', renderer1)
        register_tool_call_renderer('tool2', renderer2)

        assert len(_TOOL_CALL_RENDERERS) == 2
        assert _TOOL_CALL_RENDERERS['tool1'] == renderer1
        assert _TOOL_CALL_RENDERERS['tool2'] == renderer2

    def test_overwrite_tool_call_renderer(self):
        def renderer1(tool_call, is_suffix=False):
            return 'renderer1'

        def renderer2(tool_call, is_suffix=False):
            return 'renderer2'

        register_tool_call_renderer('test_tool', renderer1)
        register_tool_call_renderer('test_tool', renderer2)

        assert _TOOL_CALL_RENDERERS['test_tool'] == renderer2


class TestToolResultRenderer:
    def setup_method(self):
        _TOOL_RESULT_RENDERERS.clear()

    def teardown_method(self):
        _TOOL_RESULT_RENDERERS.clear()

    def test_register_tool_result_renderer(self):
        def mock_renderer(tool_message):
            return f'Result for {tool_message.tool_call.tool_name}'

        register_tool_result_renderer('test_tool', mock_renderer)

        assert 'test_tool' in _TOOL_RESULT_RENDERERS
        assert _TOOL_RESULT_RENDERERS['test_tool'] == mock_renderer

    def test_multiple_tool_result_renderers(self):
        def renderer1(tool_message):
            return 'result1'

        def renderer2(tool_message):
            return 'result2'

        register_tool_result_renderer('tool1', renderer1)
        register_tool_result_renderer('tool2', renderer2)

        assert len(_TOOL_RESULT_RENDERERS) == 2
        assert _TOOL_RESULT_RENDERERS['tool1'] == renderer1
        assert _TOOL_RESULT_RENDERERS['tool2'] == renderer2


class TestUserMsgRenderer:
    def setup_method(self):
        _USER_MSG_RENDERERS.clear()

    def teardown_method(self):
        _USER_MSG_RENDERERS.clear()

    def test_register_user_msg_renderer(self):
        def mock_renderer(user_message):
            return f'User message: {user_message.content}'

        register_user_msg_renderer('special_type', mock_renderer)

        assert 'special_type' in _USER_MSG_RENDERERS
        assert _USER_MSG_RENDERERS['special_type'] == mock_renderer

    def test_multiple_user_msg_renderers(self):
        def renderer1(user_message):
            return 'type1'

        def renderer2(user_message):
            return 'type2'

        register_user_msg_renderer('type1', renderer1)
        register_user_msg_renderer('type2', renderer2)

        assert len(_USER_MSG_RENDERERS) == 2
        assert _USER_MSG_RENDERERS['type1'] == renderer1
        assert _USER_MSG_RENDERERS['type2'] == renderer2


class TestUserMsgSuffixRenderer:
    def setup_method(self):
        _USER_MSG_SUFFIX_RENDERERS.clear()

    def teardown_method(self):
        _USER_MSG_SUFFIX_RENDERERS.clear()

    def test_register_user_msg_suffix_renderer(self):
        def mock_suffix_renderer(user_message):
            return f'Suffix for: {user_message.content}'

        register_user_msg_suffix_renderer('special_type', mock_suffix_renderer)

        assert 'special_type' in _USER_MSG_SUFFIX_RENDERERS
        assert _USER_MSG_SUFFIX_RENDERERS['special_type'] == mock_suffix_renderer

    def test_multiple_user_msg_suffix_renderers(self):
        def suffix1(user_message):
            return 'suffix1'

        def suffix2(user_message):
            return 'suffix2'

        register_user_msg_suffix_renderer('type1', suffix1)
        register_user_msg_suffix_renderer('type2', suffix2)

        assert len(_USER_MSG_SUFFIX_RENDERERS) == 2
        assert _USER_MSG_SUFFIX_RENDERERS['type1'] == suffix1
        assert _USER_MSG_SUFFIX_RENDERERS['type2'] == suffix2


class TestUserMsgContentFunc:
    def setup_method(self):
        _USER_MSG_CONTENT_FUNCS.clear()

    def teardown_method(self):
        _USER_MSG_CONTENT_FUNCS.clear()

    def test_register_user_msg_content_func(self):
        def mock_content_func(user_message):
            return f'Custom content: {user_message.content}'

        register_user_msg_content_func('custom_type', mock_content_func)

        assert 'custom_type' in _USER_MSG_CONTENT_FUNCS
        assert _USER_MSG_CONTENT_FUNCS['custom_type'] == mock_content_func

    def test_multiple_user_msg_content_funcs(self):
        def content1(user_message):
            return 'content1'

        def content2(user_message):
            return 'content2'

        register_user_msg_content_func('type1', content1)
        register_user_msg_content_func('type2', content2)

        assert len(_USER_MSG_CONTENT_FUNCS) == 2
        assert _USER_MSG_CONTENT_FUNCS['type1'] == content1
        assert _USER_MSG_CONTENT_FUNCS['type2'] == content2


class TestRegistryIntegration:
    def setup_method(self):
        _TOOL_CALL_RENDERERS.clear()
        _TOOL_RESULT_RENDERERS.clear()
        _USER_MSG_RENDERERS.clear()
        _USER_MSG_SUFFIX_RENDERERS.clear()
        _USER_MSG_CONTENT_FUNCS.clear()

    def teardown_method(self):
        _TOOL_CALL_RENDERERS.clear()
        _TOOL_RESULT_RENDERERS.clear()
        _USER_MSG_RENDERERS.clear()
        _USER_MSG_SUFFIX_RENDERERS.clear()
        _USER_MSG_CONTENT_FUNCS.clear()

    def test_all_registries_independent(self):
        def tool_call_renderer(tool_call, is_suffix=False):
            return 'tool_call'

        def tool_result_renderer(tool_message):
            return 'tool_result'

        def user_msg_renderer(user_message):
            return 'user_msg'

        def user_suffix_renderer(user_message):
            return 'user_suffix'

        def user_content_func(user_message):
            return 'user_content'

        register_tool_call_renderer('test', tool_call_renderer)
        register_tool_result_renderer('test', tool_result_renderer)
        register_user_msg_renderer('test', user_msg_renderer)
        register_user_msg_suffix_renderer('test', user_suffix_renderer)
        register_user_msg_content_func('test', user_content_func)

        assert len(_TOOL_CALL_RENDERERS) == 1
        assert len(_TOOL_RESULT_RENDERERS) == 1
        assert len(_USER_MSG_RENDERERS) == 1
        assert len(_USER_MSG_SUFFIX_RENDERERS) == 1
        assert len(_USER_MSG_CONTENT_FUNCS) == 1
