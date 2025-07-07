from unittest.mock import patch

from klaudecode.message.base import Attachment
from klaudecode.message.user import INTERRUPTED_MSG, SpecialUserMessageTypeEnum, UserMessage, compact_renderer, initialize_default_renderers, interrupted_renderer


class TestSpecialUserMessageTypeEnum:
    def test_enum_values(self):
        assert SpecialUserMessageTypeEnum.INTERRUPTED.value == 'interrupted'
        assert SpecialUserMessageTypeEnum.COMPACT_RESULT.value == 'compact_result'


class TestUserMessage:
    def test_user_message_default_values(self):
        msg = UserMessage()

        assert msg.role == 'user'
        assert msg.content == ''
        assert msg.pre_system_reminders is None
        assert msg.post_system_reminders is None
        assert msg.user_msg_type is None
        assert msg.user_raw_input is None

    def test_user_message_with_content(self):
        msg = UserMessage(content='Hello, can you help me?')

        assert msg.content == 'Hello, can you help me?'
        assert msg.role == 'user'

    def test_user_message_with_type(self):
        msg = UserMessage(content='Test message', user_msg_type='special_type')

        assert msg.user_msg_type == 'special_type'

    def test_user_message_with_raw_input(self):
        msg = UserMessage(content='Processed content', user_raw_input='Raw user input')

        assert msg.user_raw_input == 'Raw user input'

    def test_get_content_basic(self):
        msg = UserMessage(content='Basic user message')

        content = msg.get_content()

        assert len(content) == 1
        assert content[0]['type'] == 'text'
        assert content[0]['text'] == 'Basic user message'

    def test_get_content_with_pre_system_reminders(self):
        msg = UserMessage(content='Main content', pre_system_reminders=['Pre reminder 1', 'Pre reminder 2'])

        content = msg.get_content()

        assert len(content) == 3  # 2 pre + 1 main
        assert content[0]['text'] == 'Pre reminder 1'
        assert content[1]['text'] == 'Pre reminder 2'
        assert content[2]['text'] == 'Main content'

    def test_get_content_with_post_system_reminders(self):
        msg = UserMessage(content='Main content', post_system_reminders=['Post reminder 1', 'Post reminder 2'])

        content = msg.get_content()

        assert len(content) == 3  # 1 main + 2 post
        assert content[0]['text'] == 'Main content'
        assert content[1]['text'] == 'Post reminder 1'
        assert content[2]['text'] == 'Post reminder 2'

    def test_get_content_with_attachments(self):
        attachment = Attachment(path='/test/file.txt', content='file content')
        msg = UserMessage(content='Message with attachment', attachments=[attachment])

        content = msg.get_content()

        # Should have main content + attachment content
        assert len(content) >= 2
        assert content[0]['text'] == 'Message with attachment'

    @patch('klaudecode.message.registry._USER_MSG_CONTENT_FUNCS', {'custom_type': lambda msg: f'Custom: {msg.content}'})
    def test_get_content_with_custom_content_func(self):
        msg = UserMessage(content='Original content', user_msg_type='custom_type')

        content = msg.get_content()

        assert len(content) == 1
        assert content[0]['text'] == 'Custom: Original content'

    def test_get_content_all_features(self):
        msg = UserMessage(content='Main content', pre_system_reminders=['Pre reminder'], post_system_reminders=['Post reminder'])

        content = msg.get_content()

        assert len(content) == 3
        assert content[0]['text'] == 'Pre reminder'
        assert content[1]['text'] == 'Main content'
        assert content[2]['text'] == 'Post reminder'

    def test_to_openai(self):
        msg = UserMessage(content='Hello OpenAI')

        result = msg.to_openai()

        assert result['role'] == 'user'
        assert 'content' in result

    def test_to_anthropic(self):
        msg = UserMessage(content='Hello Anthropic')

        result = msg.to_anthropic()

        assert result['role'] == 'user'
        assert 'content' in result

    def test_bool_empty_content(self):
        msg = UserMessage()

        assert bool(msg) is False

    def test_bool_with_content(self):
        msg = UserMessage(content='Some content')

        assert bool(msg) is True

    def test_bool_whitespace_content(self):
        msg = UserMessage(content='   \n  \t  ')

        assert bool(msg) is False

    def test_bool_removed_message(self):
        msg = UserMessage(content='Content', removed=True)

        assert bool(msg) is False

    @patch('klaudecode.message.registry._USER_MSG_RENDERERS', {})
    def test_rich_console_default_renderer(self):
        msg = UserMessage(content='Test message')

        result = list(msg.__rich_console__(None, None))

        # Should yield the rendered message and suffix
        assert len(result) >= 1

    @patch('klaudecode.message.registry._USER_MSG_RENDERERS', {'special': lambda msg: ['Custom rendered']})
    def test_rich_console_custom_renderer(self):
        msg = UserMessage(content='Test message', user_msg_type='special')

        result = list(msg.__rich_console__(None, None))

        # Should use custom renderer
        assert len(result) >= 1

    def test_get_suffix_renderable_with_attachments(self):
        attachment1 = Attachment(type='text', path='/test/file.txt', line_count=10)
        attachment2 = Attachment(type='image', path='/test/image.png', size_str='100KB')
        attachment3 = Attachment(type='directory', path='/test/dir')

        msg = UserMessage(content='Message', attachments=[attachment1, attachment2, attachment3])

        result = list(msg.get_suffix_renderable())

        # Should yield one suffix for each attachment
        assert len(result) == 3

    def test_get_suffix_renderable_with_error_msgs(self):
        msg = UserMessage(content='Message')
        msg.set_extra_data('error_msgs', ['Error 1', 'Error 2'])

        result = list(msg.get_suffix_renderable())

        # Should yield one suffix for each error
        assert len(result) == 2

    @patch('klaudecode.message.registry._USER_MSG_SUFFIX_RENDERERS', {'special': lambda msg: ['Custom suffix']})
    def test_get_suffix_renderable_custom_suffix_renderer(self):
        msg = UserMessage(content='Message', user_msg_type='special')

        result = list(msg.get_suffix_renderable())

        # Should include custom suffix
        assert len(result) >= 1

    def test_append_pre_system_reminder_new_list(self):
        msg = UserMessage(content='Message')

        msg.append_pre_system_reminder('First reminder')

        assert msg.pre_system_reminders == ['First reminder']

    def test_append_pre_system_reminder_existing_list(self):
        msg = UserMessage(content='Message', pre_system_reminders=['Existing reminder'])

        msg.append_pre_system_reminder('New reminder')

        assert msg.pre_system_reminders == ['Existing reminder', 'New reminder']

    def test_append_post_system_reminder_new_list(self):
        msg = UserMessage(content='Message')

        msg.append_post_system_reminder('First reminder')

        assert msg.post_system_reminders == ['First reminder']

    def test_append_post_system_reminder_existing_list(self):
        msg = UserMessage(content='Message', post_system_reminders=['Existing reminder'])

        msg.append_post_system_reminder('New reminder')

        assert msg.post_system_reminders == ['Existing reminder', 'New reminder']


class TestRendererFunctions:
    def test_interrupted_renderer(self):
        msg = UserMessage(content='Interrupted message')

        result = list(interrupted_renderer(msg))

        # Should yield one rendered message
        assert len(result) == 1

    def test_compact_renderer(self):
        msg = UserMessage(content='Compacted message content')

        result = list(compact_renderer(msg))

        # Should yield rule and message
        assert len(result) == 2

    @patch('klaudecode.message.registry.register_user_msg_renderer')
    def test_initialize_default_renderers(self, mock_register):
        # Re-import to trigger initialization

        initialize_default_renderers()

        # Should register both default renderers
        assert mock_register.call_count == 2

        # Check that the correct types were registered
        call_args = [call[0] for call in mock_register.call_args_list]
        assert ('interrupted', interrupted_renderer) in call_args
        assert ('compact_result', compact_renderer) in call_args


class TestConstants:
    def test_interrupted_msg_constant(self):
        assert INTERRUPTED_MSG == 'Interrupted by user'
