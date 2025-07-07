from klaudecode.message.system import SystemMessage


class TestSystemMessage:
    def test_system_message_default_values(self):
        msg = SystemMessage()

        assert msg.role == 'system'
        assert msg.cached is False
        assert msg.content == ''

    def test_system_message_with_content(self):
        msg = SystemMessage(content='You are a helpful assistant.')

        assert msg.content == 'You are a helpful assistant.'
        assert msg.role == 'system'
        assert msg.cached is False

    def test_system_message_with_cached(self):
        msg = SystemMessage(content='System prompt', cached=True)

        assert msg.content == 'System prompt'
        assert msg.cached is True

    def test_get_content_without_cache(self):
        msg = SystemMessage(content='Test system message', cached=False)

        content = msg.get_content()

        assert len(content) == 1
        assert content[0]['type'] == 'text'
        assert content[0]['text'] == 'Test system message'
        assert content[0]['cache_control'] is None

    def test_get_content_with_cache(self):
        msg = SystemMessage(content='Cached system message', cached=True)

        content = msg.get_content()

        assert len(content) == 1
        assert content[0]['type'] == 'text'
        assert content[0]['text'] == 'Cached system message'
        assert content[0]['cache_control'] == {'type': 'ephemeral'}

    def test_get_anthropic_content_without_cache(self):
        msg = SystemMessage(content='Test system message', cached=False)

        content = msg.get_anthropic_content()

        assert content['type'] == 'text'
        assert content['text'] == 'Test system message'
        assert 'cache_control' not in content

    def test_get_anthropic_content_with_cache(self):
        msg = SystemMessage(content='Cached system message', cached=True)

        content = msg.get_anthropic_content()

        assert content['type'] == 'text'
        assert content['text'] == 'Cached system message'
        assert content['cache_control'] == {'type': 'ephemeral'}

    def test_to_openai(self):
        msg = SystemMessage(content='System prompt for OpenAI')

        result = msg.to_openai()

        assert result['role'] == 'system'
        assert len(result['content']) == 1
        assert result['content'][0]['type'] == 'text'
        assert result['content'][0]['text'] == 'System prompt for OpenAI'

    def test_to_openai_with_cache(self):
        msg = SystemMessage(content='Cached system prompt', cached=True)

        result = msg.to_openai()

        assert result['role'] == 'system'
        assert len(result['content']) == 1
        assert result['content'][0]['type'] == 'text'
        assert result['content'][0]['text'] == 'Cached system prompt'
        assert result['content'][0]['cache_control'] == {'type': 'ephemeral'}

    def test_to_anthropic(self):
        msg = SystemMessage(content='System prompt for Anthropic')

        result = msg.to_anthropic()

        assert result['type'] == 'text'
        assert result['text'] == 'System prompt for Anthropic'
        assert 'cache_control' not in result

    def test_to_anthropic_with_cache(self):
        msg = SystemMessage(content='Cached system prompt', cached=True)

        result = msg.to_anthropic()

        assert result['type'] == 'text'
        assert result['text'] == 'Cached system prompt'
        assert result['cache_control'] == {'type': 'ephemeral'}

    def test_bool_empty_content(self):
        msg = SystemMessage()

        assert bool(msg) is False

    def test_bool_with_content(self):
        msg = SystemMessage(content='System message')

        assert bool(msg) is True

    def test_bool_whitespace_content(self):
        msg = SystemMessage(content='   \n  \t  ')

        assert bool(msg) is True  # Any non-empty string is truthy

    def test_bool_empty_string_content(self):
        msg = SystemMessage(content='')

        assert bool(msg) is False

    def test_rich_console_returns_empty(self):
        msg = SystemMessage(content='Test message')

        # The __rich_console__ method has a return statement without yielding anything
        # This is likely intentional to not display system messages in the console
        result = list(msg.__rich_console__(None, None))

        assert result == []
