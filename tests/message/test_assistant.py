from klaudecode.message.assistant import AgentUsage, AIMessage, CompletionUsage
from klaudecode.message.tool_call import ToolCall


class TestCompletionUsage:
    def test_completion_usage_initialization(self):
        usage = CompletionUsage(completion_tokens=100, prompt_tokens=50, total_tokens=150)

        assert usage.completion_tokens == 100
        assert usage.prompt_tokens == 50
        assert usage.total_tokens == 150


class TestAIMessage:
    def test_ai_message_default_values(self):
        msg = AIMessage()

        assert msg.role == 'assistant'
        assert msg.tool_calls == {}
        assert msg.thinking_content == ''
        assert msg.thinking_signature == ''
        assert msg.finish_reason == 'stop'
        assert msg.usage is None

    def test_ai_message_with_content(self):
        msg = AIMessage(content='Hello, how can I help?')

        assert msg.content == 'Hello, how can I help?'
        assert msg.role == 'assistant'

    def test_get_content_text_only(self):
        msg = AIMessage(content='Test message')

        content = msg.get_content()

        assert len(content) == 1
        assert content[0]['type'] == 'text'
        assert content[0]['text'] == 'Test message'

    def test_get_content_with_thinking(self):
        msg = AIMessage(thinking_content='Let me think about this', thinking_signature='sig123', content='My response')

        content = msg.get_content()

        assert len(content) == 2
        assert content[0]['type'] == 'thinking'
        assert content[0]['thinking'] == 'Let me think about this'
        assert content[0]['signature'] == 'sig123'
        assert content[1]['type'] == 'text'
        assert content[1]['text'] == 'My response'

    def test_get_content_with_tool_calls(self):
        tool_call = ToolCall(id='call_123', tool_name='test_tool', tool_args_dict={'param': 'value'})
        msg = AIMessage(content='Using a tool', tool_calls={'call_123': tool_call})

        content = msg.get_content()

        assert len(content) == 2
        assert content[0]['type'] == 'text'
        assert content[0]['text'] == 'Using a tool'
        assert content[1]['type'] == 'text'
        assert content[1]['text'] == tool_call.tool_args

    def test_to_openai_basic(self):
        msg = AIMessage(content='Hello world')

        result = msg.to_openai()

        assert result['role'] == 'assistant'
        assert result['content'] == 'Hello world'
        assert 'tool_calls' not in result

    def test_to_openai_with_tool_calls(self):
        tool_call = ToolCall(id='call_123', tool_name='test_tool', tool_args_dict={'param': 'value'})
        msg = AIMessage(content='Using tool', tool_calls={'call_123': tool_call})

        result = msg.to_openai()

        assert result['role'] == 'assistant'
        assert result['content'] == 'Using tool'
        assert 'tool_calls' in result
        assert len(result['tool_calls']) == 1

    def test_to_anthropic_basic(self):
        msg = AIMessage(content='Hello world')

        result = msg.to_anthropic()

        assert result['role'] == 'assistant'
        assert len(result['content']) == 1
        assert result['content'][0]['type'] == 'text'
        assert result['content'][0]['text'] == 'Hello world'

    def test_to_anthropic_with_thinking_and_tool_calls(self):
        tool_call = ToolCall(id='call_123', tool_name='test_tool', tool_args_dict={'param': 'value'})
        msg = AIMessage(thinking_content='Thinking...', thinking_signature='sig123', content='Response', tool_calls={'call_123': tool_call})

        result = msg.to_anthropic()

        assert result['role'] == 'assistant'
        assert len(result['content']) == 3

        # Thinking content
        assert result['content'][0]['type'] == 'thinking'
        assert result['content'][0]['thinking'] == 'Thinking...'
        assert result['content'][0]['signature'] == 'sig123'

        # Text content
        assert result['content'][1]['type'] == 'text'
        assert result['content'][1]['text'] == 'Response'

        # Tool call
        assert result['content'][2]['type'] == 'tool_use'

    def test_bool_empty_message(self):
        msg = AIMessage()

        assert bool(msg) is False

    def test_bool_with_content(self):
        msg = AIMessage(content='Hello')

        assert bool(msg) is True

    def test_bool_with_thinking(self):
        msg = AIMessage(thinking_content='Thinking...')

        assert bool(msg) is True

    def test_bool_with_tool_calls(self):
        tool_call = ToolCall(id='call_123', tool_name='test_tool', tool_args_dict={'param': 'value'})
        msg = AIMessage(tool_calls={'call_123': tool_call})

        assert bool(msg) is True

    def test_bool_removed_message(self):
        msg = AIMessage(content='Hello', removed=True)

        assert bool(msg) is False

    def test_bool_whitespace_content(self):
        msg = AIMessage(content='   \n  \t  ')

        assert bool(msg) is False

    def test_merge_messages(self):
        msg1 = AIMessage(
            content='Hello',
            thinking_content='First thought',
            thinking_signature='sig1',
            finish_reason='length',
            usage=CompletionUsage(completion_tokens=10, prompt_tokens=5, total_tokens=15),
        )

        tool_call = ToolCall(id='call_123', tool_name='tool1', tool_args_dict={})
        msg2 = AIMessage(
            content=' World',
            thinking_content=' Second thought',
            thinking_signature='sig2',
            finish_reason='stop',
            usage=CompletionUsage(completion_tokens=20, prompt_tokens=10, total_tokens=30),
            tool_calls={'call_123': tool_call},
        )

        result = msg1.merge(msg2)

        assert result.content == 'Hello World'
        assert result.thinking_content == 'First thought Second thought'
        assert result.thinking_signature == 'sig1sig2'
        assert result.finish_reason == 'stop'
        assert result.usage.completion_tokens == 30
        assert result.usage.prompt_tokens == 15
        assert result.usage.total_tokens == 45
        assert 'call_123' in result.tool_calls

    def test_merge_with_none_usage(self):
        msg1 = AIMessage(content='Hello')
        msg2 = AIMessage(content=' World')

        result = msg1.merge(msg2)

        assert result.content == 'Hello World'
        assert result.usage is None


class TestAgentUsage:
    def test_agent_usage_default_values(self):
        usage = AgentUsage()

        assert usage.total_llm_calls == 0
        assert usage.total_input_tokens == 0
        assert usage.total_output_tokens == 0

    def test_update_with_ai_message(self):
        usage = AgentUsage()
        ai_msg = AIMessage(usage=CompletionUsage(completion_tokens=100, prompt_tokens=50, total_tokens=150))

        usage.update(ai_msg)

        assert usage.total_llm_calls == 1
        assert usage.total_input_tokens == 50
        assert usage.total_output_tokens == 100

    def test_update_with_ai_message_no_usage(self):
        usage = AgentUsage(total_llm_calls=1, total_input_tokens=10, total_output_tokens=20)
        ai_msg = AIMessage()

        usage.update(ai_msg)

        assert usage.total_llm_calls == 2
        assert usage.total_input_tokens == 10
        assert usage.total_output_tokens == 20

    def test_update_multiple_calls(self):
        usage = AgentUsage()
        ai_msg1 = AIMessage(usage=CompletionUsage(completion_tokens=50, prompt_tokens=25, total_tokens=75))
        ai_msg2 = AIMessage(usage=CompletionUsage(completion_tokens=30, prompt_tokens=15, total_tokens=45))

        usage.update(ai_msg1)
        usage.update(ai_msg2)

        assert usage.total_llm_calls == 2
        assert usage.total_input_tokens == 40
        assert usage.total_output_tokens == 80

    def test_update_with_usage(self):
        usage1 = AgentUsage(total_llm_calls=2, total_input_tokens=100, total_output_tokens=200)
        usage2 = AgentUsage(total_llm_calls=3, total_input_tokens=150, total_output_tokens=300)

        usage1.update_with_usage(usage2)

        assert usage1.total_llm_calls == 5
        assert usage1.total_input_tokens == 250
        assert usage1.total_output_tokens == 500
