import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest

from klaudecode.agent import Agent, get_main_agent
from klaudecode.agent_state import AgentState
from klaudecode.config import ConfigModel
from klaudecode.message import UserMessage
from klaudecode.session import Session
from klaudecode.tools import BASIC_TOOLS


class TestAgent:
    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            yield Path(temp_dir)

    @pytest.fixture
    def mock_session(self, temp_dir):
        session = Mock(spec=Session)
        session.work_dir = temp_dir
        session.messages = Mock()
        session.messages.print_all_message = Mock()
        session.messages.get_last_message = Mock(return_value=None)
        session.save = Mock()
        return session

    @pytest.fixture
    def mock_config(self):
        return Mock(spec=ConfigModel)

    @pytest.fixture
    def mock_agent_state(self, mock_session, mock_config):
        state = Mock(spec=AgentState)
        state.session = mock_session
        state.config = mock_config
        state.print_switch = True
        state.plan_mode_activated = False
        state.available_tools = BASIC_TOOLS
        state.mcp_manager = None
        state.initialize_llm = Mock()
        state.get_all_tools = Mock(return_value=BASIC_TOOLS)
        return state

    @pytest.fixture
    def agent(self, mock_agent_state):
        with (
            patch('klaudecode.agent.AgentExecutor') as mock_executor_class,
            patch('klaudecode.agent.InputSession') as mock_input_session_class,
            patch('klaudecode.agent.UserInputHandler') as mock_user_input_handler_class,
            patch('klaudecode.user_command.custom_command_manager') as mock_command_manager,
        ):
            mock_executor = Mock()
            mock_executor_class.return_value = mock_executor

            mock_input_session = Mock()
            mock_input_session_class.return_value = mock_input_session

            mock_user_input_handler = Mock()
            mock_user_input_handler_class.return_value = mock_user_input_handler

            mock_command_manager.discover_and_register_commands = Mock()

            agent = Agent(mock_agent_state)
            agent.agent_executor = mock_executor
            agent.input_session = mock_input_session
            agent.user_input_handler = mock_user_input_handler

            return agent

    def test_agent_initialization(self, mock_agent_state):
        with (
            patch('klaudecode.agent.AgentExecutor') as mock_executor_class,
            patch('klaudecode.agent.InputSession') as mock_input_session_class,
            patch('klaudecode.agent.UserInputHandler') as mock_user_input_handler_class,
            patch('klaudecode.user_command.custom_command_manager') as mock_command_manager,
        ):
            mock_command_manager.discover_and_register_commands = Mock()

            agent = Agent(mock_agent_state)

            assert agent.agent_state == mock_agent_state
            mock_executor_class.assert_called_once_with(mock_agent_state)
            mock_input_session_class.assert_called_once_with(mock_agent_state.session.work_dir)
            mock_user_input_handler_class.assert_called_once_with(mock_agent_state, agent.input_session)
            mock_command_manager.discover_and_register_commands.assert_called_once_with(mock_agent_state.session.work_dir)

    def test_agent_initialization_command_discovery_error(self, mock_agent_state):
        with (
            patch('klaudecode.agent.AgentExecutor'),
            patch('klaudecode.agent.InputSession'),
            patch('klaudecode.agent.UserInputHandler'),
            patch('klaudecode.user_command.custom_command_manager') as mock_command_manager,
            patch('klaudecode.agent.console') as mock_console,
        ):
            mock_command_manager.discover_and_register_commands = Mock(side_effect=Exception('Command error'))

            agent = Agent(mock_agent_state)

            assert agent.agent_state == mock_agent_state
            mock_console.print.assert_called()

    @pytest.mark.asyncio
    async def test_chat_interactive_quit_command(self, agent, mock_agent_state):
        agent.input_session.prompt_async = AsyncMock(return_value='quit')

        await agent.chat_interactive()

        mock_agent_state.initialize_llm.assert_called_once()
        mock_agent_state.session.messages.print_all_message.assert_called_once()
        mock_agent_state.session.save.assert_called()

    @pytest.mark.asyncio
    async def test_chat_interactive_exit_command(self, agent, mock_agent_state):
        agent.input_session.prompt_async = AsyncMock(return_value='exit')

        await agent.chat_interactive()

        mock_agent_state.initialize_llm.assert_called_once()
        mock_agent_state.session.save.assert_called()

    @pytest.mark.asyncio
    async def test_chat_interactive_with_first_message(self, agent, mock_agent_state):
        agent.user_input_handler.handle = AsyncMock(return_value=True)
        agent.agent_executor.run = AsyncMock()
        agent.input_session.prompt_async = AsyncMock(return_value='quit')

        with patch.object(agent, '_handle_claudemd_reminder') as mock_handle_claudemd, patch.object(agent, '_handle_empty_todo_reminder') as mock_handle_todo:
            await agent.chat_interactive(first_message='Hello')

            agent.user_input_handler.handle.assert_called_with('Hello', print_msg=True)
            agent.agent_executor.run.assert_called_once()
            mock_handle_claudemd.assert_called_once()
            mock_handle_todo.assert_called_once()

    @pytest.mark.asyncio
    async def test_chat_interactive_no_agent_run_needed(self, agent, mock_agent_state):
        agent.user_input_handler.handle = AsyncMock(return_value=False)
        agent.input_session.prompt_async = AsyncMock(return_value='quit')

        await agent.chat_interactive()

        mock_agent_state.session.save.assert_called()

    @pytest.mark.asyncio
    async def test_chat_interactive_with_mcp_cleanup(self, agent, mock_agent_state):
        mock_mcp_manager = Mock()
        mock_mcp_manager.shutdown = AsyncMock()
        mock_agent_state.mcp_manager = mock_mcp_manager
        agent.input_session.prompt_async = AsyncMock(return_value='quit')

        with patch('klaudecode.agent.cleanup_all_backups') as mock_cleanup:
            await agent.chat_interactive()

            mock_mcp_manager.shutdown.assert_called_once()
            mock_cleanup.assert_called_once()

    @pytest.mark.asyncio
    async def test_headless_run(self, agent, mock_agent_state):
        agent.user_input_handler.handle = AsyncMock(return_value=True)

        with (
            patch.object(agent, '_headless_run_with_status_display') as mock_headless_run,
            patch.object(agent, '_handle_claudemd_reminder') as mock_handle_claudemd,
            patch.object(agent, '_handle_empty_todo_reminder') as mock_handle_todo,
            patch('klaudecode.agent.console') as mock_console,
        ):
            mock_headless_run.return_value = 'Result'

            await agent.headless_run('Test input')

            mock_agent_state.initialize_llm.assert_called_once()
            agent.user_input_handler.handle.assert_called_with('Test input', print_msg=False)
            assert mock_agent_state.print_switch is False
            assert agent.agent_executor.tool_handler.show_live is False
            mock_handle_claudemd.assert_called_once()
            mock_handle_todo.assert_called_once()
            mock_headless_run.assert_called_once()
            mock_console.print.assert_called_with('Result')

    @pytest.mark.asyncio
    async def test_headless_run_no_agent_run_needed(self, agent, mock_agent_state):
        agent.user_input_handler.handle = AsyncMock(return_value=False)

        await agent.headless_run('Test input')

        mock_agent_state.initialize_llm.assert_called_once()
        agent.user_input_handler.handle.assert_called_with('Test input', print_msg=False)

    @pytest.mark.asyncio
    async def test_headless_run_with_status_display(self, agent, mock_agent_state):
        agent.agent_executor.run = AsyncMock(return_value='Success')

        with patch('klaudecode.agent.render_dot_status') as mock_render_status:
            mock_status = Mock()
            mock_status.start = Mock()
            mock_status.stop = Mock()
            mock_status.update = Mock()
            mock_render_status.return_value = mock_status

            result = await agent._headless_run_with_status_display()

            assert result == 'Success'
            mock_status.start.assert_called_once()
            mock_status.stop.assert_called_once()

    def test_handle_claudemd_reminder(self, agent, mock_agent_state):
        mock_user_message = Mock(spec=UserMessage)
        mock_user_message.append_pre_system_reminder = Mock()
        mock_agent_state.session.messages.get_last_message = Mock(return_value=mock_user_message)

        with patch('klaudecode.agent.get_context_reminder') as mock_get_reminder:
            mock_get_reminder.return_value = 'Test reminder'

            agent._handle_claudemd_reminder()

            mock_get_reminder.assert_called_once_with(mock_agent_state.session.work_dir)
            mock_user_message.append_pre_system_reminder.assert_called_once_with('Test reminder')

    @pytest.mark.asyncio
    async def test_get_main_agent(self, temp_dir):
        mock_session = Mock(spec=Session)
        mock_config = Mock(spec=ConfigModel)

        with patch('klaudecode.agent.AgentState') as mock_agent_state_class, patch('klaudecode.agent.Agent') as mock_agent_class:
            mock_agent_state = Mock()
            mock_agent_state.initialize_mcp = AsyncMock()
            mock_agent_state_class.return_value = mock_agent_state

            mock_agent = Mock()
            mock_agent_class.return_value = mock_agent

            result = await get_main_agent(mock_session, mock_config, enable_mcp=True)

            mock_agent_state_class.assert_called_once()
            mock_agent_state.initialize_mcp.assert_called_once()
            mock_agent_class.assert_called_once_with(mock_agent_state)
            assert result == mock_agent

    @pytest.mark.asyncio
    async def test_get_main_agent_without_mcp(self, temp_dir):
        mock_session = Mock(spec=Session)
        mock_config = Mock(spec=ConfigModel)

        with patch('klaudecode.agent.AgentState') as mock_agent_state_class, patch('klaudecode.agent.Agent') as mock_agent_class:
            mock_agent_state = Mock()
            mock_agent_state.initialize_mcp = AsyncMock()
            mock_agent_state_class.return_value = mock_agent_state

            mock_agent = Mock()
            mock_agent_class.return_value = mock_agent

            result = await get_main_agent(mock_session, mock_config, enable_mcp=False)

            mock_agent_state_class.assert_called_once()
            mock_agent_state.initialize_mcp.assert_not_called()
            mock_agent_class.assert_called_once_with(mock_agent_state)
            assert result == mock_agent
