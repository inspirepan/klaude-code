from pathlib import Path
from unittest.mock import patch

import pytest

from klaudecode.message import AIMessage, ToolCall, ToolMessage, UserMessage
from klaudecode.session import Session
from klaudecode.user_command.command_output import OutputCommand
from klaudecode.user_input import UserInput


@pytest.fixture
def output_command():
    return OutputCommand()


@pytest.fixture
def mock_agent_state():
    work_dir = Path('/test/work/dir')
    session = Session(work_dir=work_dir)

    user_msg = UserMessage(content='这是一个测试问题')
    session.messages.messages.append(user_msg)

    ai_msg = AIMessage(content='This is a test AI response with content.')
    session.messages.messages.append(ai_msg)

    class MockAgentState:
        def __init__(self):
            self.session = session

    return MockAgentState()


@pytest.fixture
def mock_agent_state_with_task():
    work_dir = Path('/test/work/dir')
    session = Session(work_dir=work_dir)

    user_msg = UserMessage(content='请帮我分析代码')
    session.messages.messages.append(user_msg)

    ai_msg = AIMessage(content='我来帮你分析代码。')
    task_call = ToolCall(id='task_123', tool_name='Task', tool_args_dict={'description': '分析代码结构', 'prompt': '请分析项目的代码结构'}, status='success')
    ai_msg.tool_calls['task_123'] = task_call
    session.messages.messages.append(ai_msg)

    tool_msg = ToolMessage(tool_call_id='task_123', tool_call_cache=task_call, content='代码分析结果：项目包含3个主要模块...')
    session.messages.messages.append(tool_msg)

    final_ai_msg = AIMessage(content='根据分析结果，我建议...')
    session.messages.messages.append(final_ai_msg)

    class MockAgentState:
        def __init__(self):
            self.session = session

    return MockAgentState()


@pytest.fixture
def mock_agent_state_with_multiple_conversations():
    work_dir = Path('/test/work/dir')
    session = Session(work_dir=work_dir)

    # First conversation
    user_msg1 = UserMessage(content='请帮我分析代码')
    session.messages.messages.append(user_msg1)

    ai_msg1 = AIMessage(content='我来帮你分析代码。')
    task_call1 = ToolCall(id='task_123', tool_name='Task', tool_args_dict={'description': '分析代码结构', 'prompt': '请分析项目的代码结构'}, status='success')
    ai_msg1.tool_calls['task_123'] = task_call1
    session.messages.messages.append(ai_msg1)

    tool_msg1 = ToolMessage(tool_call_id='task_123', tool_call_cache=task_call1, content='代码分析结果：项目包含3个主要模块...')
    session.messages.messages.append(tool_msg1)

    final_ai_msg1 = AIMessage(content='根据分析结果，我建议...')
    session.messages.messages.append(final_ai_msg1)

    # Second conversation
    user_msg2 = UserMessage(content='现在帮我优化性能')
    session.messages.messages.append(user_msg2)

    ai_msg2 = AIMessage(content='我来帮你优化性能。')
    task_call2 = ToolCall(id='task_456', tool_name='Task', tool_args_dict={'description': '性能分析', 'prompt': '分析性能瓶颈'}, status='success')
    ai_msg2.tool_calls['task_456'] = task_call2
    session.messages.messages.append(ai_msg2)

    tool_msg2 = ToolMessage(tool_call_id='task_456', tool_call_cache=task_call2, content='性能分析结果：发现内存泄漏...')
    session.messages.messages.append(tool_msg2)

    final_ai_msg2 = AIMessage(content='基于性能分析，建议使用...')
    session.messages.messages.append(final_ai_msg2)

    class MockAgentState:
        def __init__(self):
            self.session = session

    return MockAgentState()


class TestOutputCommand:
    def test_get_name(self, output_command):
        assert output_command.get_name() == 'output'

    def test_get_command_desc(self, output_command):
        desc = output_command.get_command_desc()
        assert 'markdown file' in desc
        assert 'session' in desc

    @pytest.mark.asyncio
    @patch('os.system')
    @patch('os.makedirs')
    async def test_handle_with_ai_message(self, mock_makedirs, mock_os_system, output_command, mock_agent_state, tmp_path):
        mock_agent_state.session.work_dir = tmp_path

        user_input = UserInput(command_name='output', cleaned_input='', raw_input='/output')

        result = await output_command.handle(mock_agent_state, user_input)

        assert result.user_msg is not None
        assert 'saved to' in result.user_msg.content
        assert 'opened' in result.user_msg.content
        assert not result.need_agent_run
        assert result.need_render_suffix

        assert result.user_msg.get_extra_data('output_file') is not None
        assert result.user_msg.get_extra_data('content_length') > 0

        mock_os_system.assert_called_once()

        output_file = result.user_msg.get_extra_data('output_file')
        with open(output_file, 'r', encoding='utf-8') as f:
            content = f.read()
            assert '这是一个测试问题' in content
            assert 'This is a test AI response with content.' in content

    @pytest.mark.asyncio
    @patch('os.system')
    async def test_handle_with_task_tools(self, mock_os_system, output_command, mock_agent_state_with_task, tmp_path):
        mock_agent_state_with_task.session.work_dir = tmp_path

        user_input = UserInput(command_name='output', cleaned_input='', raw_input='/output')

        result = await output_command.handle(mock_agent_state_with_task, user_input)

        assert result.user_msg is not None
        assert 'saved to' in result.user_msg.content

        output_file = result.user_msg.get_extra_data('output_file')
        with open(output_file, 'r', encoding='utf-8') as f:
            content = f.read()
            assert '# Task: 分析代码结构' in content
            assert '代码分析结果：项目包含3个主要模块...' in content
            assert '# User: 请帮我分析代码' in content
            assert '根据分析结果，我建议...' in content

    @pytest.mark.asyncio
    @patch('os.system')
    async def test_handle_with_multiple_conversations(self, mock_os_system, output_command, mock_agent_state_with_multiple_conversations, tmp_path):
        mock_agent_state_with_multiple_conversations.session.work_dir = tmp_path

        user_input = UserInput(command_name='output', cleaned_input='', raw_input='/output')

        result = await output_command.handle(mock_agent_state_with_multiple_conversations, user_input)

        assert result.user_msg is not None
        assert 'saved to' in result.user_msg.content

        output_file = result.user_msg.get_extra_data('output_file')
        with open(output_file, 'r', encoding='utf-8') as f:
            content = f.read()

            # Check for first conversation section
            assert '# User: 请帮我分析代码' in content
            assert '根据分析结果，我建议...' in content
            assert '# Task: 分析代码结构' in content
            assert '代码分析结果：项目包含3个主要模块...' in content

            # Check for second conversation section
            assert '# User: 现在帮我优化性能' in content
            assert '基于性能分析，建议使用...' in content
            assert '# Task: 性能分析' in content
            assert '性能分析结果：发现内存泄漏...' in content

    @pytest.mark.asyncio
    @patch('os.system')
    async def test_handle_no_ai_message(self, mock_os_system, output_command, tmp_path):
        work_dir = tmp_path
        session = Session(work_dir=work_dir)

        class MockAgentState:
            def __init__(self):
                self.session = session

        mock_agent_state = MockAgentState()

        user_input = UserInput(command_name='output', cleaned_input='', raw_input='/output')

        result = await output_command.handle(mock_agent_state, user_input)

        assert result.user_msg is not None
        assert 'No AI message with content found' in result.user_msg.content
        assert not result.need_agent_run
        assert result.need_render_suffix

    def test_render_user_msg_suffix(self, output_command):
        from klaudecode.message import UserMessage

        user_msg = UserMessage(content='test')
        user_msg.set_extra_data('output_file', '/tmp/test.md')
        user_msg.set_extra_data('content_length', 100)

        result = list(output_command.render_user_msg_suffix(user_msg))

        assert len(result) == 2
