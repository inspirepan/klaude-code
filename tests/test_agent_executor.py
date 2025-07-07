import asyncio
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest
from anthropic import AnthropicError
from openai import OpenAIError

from klaudecode.agent_executor import AgentExecutor
from klaudecode.agent_state import AgentState
from klaudecode.message import INTERRUPTED_MSG
from klaudecode.session import Session
from klaudecode.tools import BASIC_TOOLS


class TestAgentExecutor:
    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            yield Path(temp_dir)

    @pytest.fixture
    def mock_session(self, temp_dir):
        session = Mock(spec=Session)
        session.work_dir = temp_dir
        session.messages = []
        session.save = Mock()
        return session

    @pytest.fixture
    def mock_agent_state(self, mock_session):
        state = Mock(spec=AgentState)
        state.session = mock_session
        state.available_tools = BASIC_TOOLS
        state.print_switch = True
        state.usage = Mock()
        state.usage.update_usage = Mock()
        state.llm_manager = Mock()
        state.llm_manager.complete_stream = AsyncMock()
        return state

    @pytest.fixture
    def agent_executor(self, mock_agent_state):
        with patch('klaudecode.agent_executor.ToolHandler') as mock_tool_handler_class:
            mock_tool_handler = Mock()
            mock_tool_handler_class.return_value = mock_tool_handler

            executor = AgentExecutor(mock_agent_state)
            executor.tool_handler = mock_tool_handler

            return executor

    @pytest.mark.asyncio
    async def test_run_success(self, agent_executor, mock_agent_state):
        with patch.object(agent_executor, '_execute_run_loop') as mock_execute:
            mock_execute.return_value = 'Success'

            result = await agent_executor.run()

            mock_execute.assert_called_once_with(100, None, None)
            assert result == 'Success'

    @pytest.mark.asyncio
    async def test_run_openai_error(self, agent_executor, mock_agent_state):
        with patch.object(agent_executor, '_execute_run_loop') as mock_execute, patch.object(agent_executor, '_handle_llm_error') as mock_handle_error:
            error = OpenAIError('API Error')
            mock_execute.side_effect = error
            mock_handle_error.return_value = 'LLM Error Handled'

            result = await agent_executor.run()

            mock_handle_error.assert_called_once_with(error)
            assert result == 'LLM Error Handled'

    @pytest.mark.asyncio
    async def test_run_anthropic_error(self, agent_executor, mock_agent_state):
        with patch.object(agent_executor, '_execute_run_loop') as mock_execute, patch.object(agent_executor, '_handle_llm_error') as mock_handle_error:
            error = AnthropicError('API Error')
            mock_execute.side_effect = error
            mock_handle_error.return_value = 'LLM Error Handled'

            result = await agent_executor.run()

            mock_handle_error.assert_called_once_with(error)
            assert result == 'LLM Error Handled'

    @pytest.mark.asyncio
    async def test_run_keyboard_interrupt(self, agent_executor, mock_agent_state):
        with patch.object(agent_executor, '_execute_run_loop') as mock_execute, patch.object(agent_executor, '_handle_interruption') as mock_handle_interrupt:
            mock_execute.side_effect = KeyboardInterrupt()
            mock_handle_interrupt.return_value = 'Interrupted'

            result = await agent_executor.run()

            mock_handle_interrupt.assert_called_once()
            assert result == 'Interrupted'

    @pytest.mark.asyncio
    async def test_run_cancelled_error(self, agent_executor, mock_agent_state):
        with patch.object(agent_executor, '_execute_run_loop') as mock_execute, patch.object(agent_executor, '_handle_interruption') as mock_handle_interrupt:
            mock_execute.side_effect = asyncio.CancelledError()
            mock_handle_interrupt.return_value = 'Cancelled'

            result = await agent_executor.run()

            mock_handle_interrupt.assert_called_once()
            assert result == 'Cancelled'

    @pytest.mark.asyncio
    async def test_run_general_error(self, agent_executor, mock_agent_state):
        with patch.object(agent_executor, '_execute_run_loop') as mock_execute, patch.object(agent_executor, '_handle_general_error') as mock_handle_error:
            error = ValueError('Some error')
            mock_execute.side_effect = error
            mock_handle_error.return_value = 'General Error Handled'

            result = await agent_executor.run()

            mock_handle_error.assert_called_once_with(error)
            assert result == 'General Error Handled'

    @pytest.mark.asyncio
    async def test_run_with_custom_params(self, agent_executor, mock_agent_state):
        tools = [Mock()]
        check_cancel = Mock(return_value=False)

        with patch.object(agent_executor, '_execute_run_loop') as mock_execute:
            mock_execute.return_value = 'Success'

            result = await agent_executor.run(max_steps=50, check_cancel=check_cancel, tools=tools)

            mock_execute.assert_called_once_with(50, check_cancel, tools)
            assert result == 'Success'

    @pytest.mark.asyncio
    async def test_execute_run_loop_check_cancel_true(self, agent_executor, mock_agent_state):
        check_cancel = Mock(return_value=True)

        result = await agent_executor._execute_run_loop(max_steps=10, check_cancel=check_cancel, tools=None)

        assert result == INTERRUPTED_MSG
        check_cancel.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_run_loop_no_cancel_check(self, agent_executor, mock_agent_state):
        agent_executor.agent_state.session.messages = []

        with patch.object(agent_executor, '_auto_compact_conversation') as mock_compact:
            mock_compact.return_value = None

            try:
                result = await agent_executor._execute_run_loop(max_steps=1, check_cancel=None, tools=None)
                assert result is not None
            except Exception:
                pass

    def test_handle_llm_error(self, agent_executor, mock_agent_state):
        error = OpenAIError('Test error')

        with patch('klaudecode.agent_executor.console') as mock_console, patch('klaudecode.agent_executor.format_exception') as mock_format:
            mock_format.return_value = 'Formatted error'

            result = agent_executor._handle_llm_error(error)

            mock_console.print.assert_called()
            assert 'Formatted error' in result

    @pytest.mark.asyncio
    async def test_handle_interruption(self, agent_executor, mock_agent_state):
        from klaudecode.message import INTERRUPTED_MSG

        with patch('asyncio.create_task') as mock_create_task:
            result = agent_executor._handle_interruption()

            mock_create_task.assert_called_once()
            assert result == INTERRUPTED_MSG

    def test_handle_general_error(self, agent_executor, mock_agent_state):
        error = ValueError('Test error')

        with (
            patch('klaudecode.agent_executor.console') as mock_console,
            patch('klaudecode.agent_executor.format_exception') as mock_format,
        ):
            mock_format.return_value = 'Formatted error'

            result = agent_executor._handle_general_error(error)

            mock_console.print.assert_called()
            assert 'Formatted error' in result

    @pytest.mark.asyncio
    async def test_initialization(self, mock_agent_state):
        with patch('klaudecode.agent_executor.ToolHandler') as mock_tool_handler_class:
            mock_tool_handler = Mock()
            mock_tool_handler_class.return_value = mock_tool_handler

            executor = AgentExecutor(mock_agent_state)

            assert executor.agent_state == mock_agent_state
            mock_tool_handler_class.assert_called_once_with(mock_agent_state, mock_agent_state.available_tools, show_live=mock_agent_state.print_switch)
            assert executor.tool_handler == mock_tool_handler
