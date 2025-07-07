import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest

from klaudecode.agent_state import AgentState
from klaudecode.config import ConfigModel
from klaudecode.message import AgentUsage
from klaudecode.session import Session
from klaudecode.tools import BASIC_TOOLS


class TestAgentState:
    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            yield Path(temp_dir)

    @pytest.fixture
    def mock_session(self, temp_dir):
        session = Mock(spec=Session)
        session.work_dir = temp_dir
        return session

    @pytest.fixture
    def mock_config(self):
        return Mock(spec=ConfigModel)

    def test_agent_state_initialization_defaults(self, mock_session):
        agent_state = AgentState(mock_session)

        assert agent_state.session == mock_session
        assert agent_state.config is None
        assert agent_state.print_switch is True
        assert agent_state.plan_mode_activated is False
        assert agent_state.available_tools == []
        assert agent_state._cached_all_tools is None
        assert agent_state._tools_cache_dirty is True
        assert agent_state.llm_manager is None
        assert agent_state.mcp_manager is None
        assert isinstance(agent_state.usage, AgentUsage)

    def test_agent_state_initialization_with_params(self, mock_session, mock_config):
        available_tools = BASIC_TOOLS

        agent_state = AgentState(session=mock_session, config=mock_config, available_tools=available_tools, print_switch=False)

        assert agent_state.session == mock_session
        assert agent_state.config == mock_config
        assert agent_state.print_switch is False
        assert agent_state.available_tools == available_tools

    def test_initialize_llm_first_time(self, mock_session, mock_config):
        agent_state = AgentState(mock_session, config=mock_config)

        with patch('klaudecode.agent_state.LLMManager') as mock_llm_manager_class:
            mock_llm_manager = Mock()
            mock_llm_manager_class.return_value = mock_llm_manager

            agent_state.initialize_llm()

            mock_llm_manager_class.assert_called_once()
            mock_llm_manager.initialize_from_config.assert_called_once_with(mock_config)
            assert agent_state.llm_manager == mock_llm_manager

    def test_initialize_llm_already_initialized(self, mock_session, mock_config):
        agent_state = AgentState(mock_session, config=mock_config)

        existing_manager = Mock()
        agent_state.llm_manager = existing_manager

        agent_state.initialize_llm()

        existing_manager.initialize_from_config.assert_called_once_with(mock_config)

    @pytest.mark.asyncio
    async def test_initialize_mcp_first_time(self, mock_session):
        agent_state = AgentState(mock_session)

        with patch('klaudecode.agent_state.MCPManager') as mock_mcp_manager_class:
            mock_mcp_manager = Mock()
            mock_mcp_manager.initialize = AsyncMock(return_value=True)
            mock_mcp_manager_class.return_value = mock_mcp_manager

            result = await agent_state.initialize_mcp()

            mock_mcp_manager_class.assert_called_once_with(mock_session.work_dir)
            mock_mcp_manager.initialize.assert_called_once()
            assert agent_state.mcp_manager == mock_mcp_manager
            assert agent_state._tools_cache_dirty is True
            assert result is True

    @pytest.mark.asyncio
    async def test_initialize_mcp_already_initialized(self, mock_session):
        agent_state = AgentState(mock_session)

        existing_manager = Mock()
        agent_state.mcp_manager = existing_manager

        result = await agent_state.initialize_mcp()

        assert result is True

    def test_get_all_tools_no_cache(self, mock_session):
        available_tools = BASIC_TOOLS
        agent_state = AgentState(mock_session, available_tools=available_tools)

        tools = agent_state.get_all_tools()

        assert tools == available_tools
        assert agent_state._cached_all_tools == available_tools
        assert agent_state._tools_cache_dirty is False

    def test_get_all_tools_with_cache(self, mock_session):
        available_tools = BASIC_TOOLS
        agent_state = AgentState(mock_session, available_tools=available_tools)

        cached_tools = [Mock()]
        agent_state._cached_all_tools = cached_tools
        agent_state._tools_cache_dirty = False

        tools = agent_state.get_all_tools()

        assert tools == cached_tools

    def test_get_all_tools_with_mcp_tools(self, mock_session):
        available_tools = BASIC_TOOLS[:2]
        agent_state = AgentState(mock_session, available_tools=available_tools)

        mock_mcp_manager = Mock()
        mock_mcp_tools = [Mock(), Mock()]
        mock_mcp_manager.is_initialized.return_value = True
        mock_mcp_manager.get_mcp_tools.return_value = mock_mcp_tools
        agent_state.mcp_manager = mock_mcp_manager

        tools = agent_state.get_all_tools()

        expected_tools = available_tools + mock_mcp_tools
        assert tools == expected_tools
        assert agent_state._cached_all_tools == expected_tools

    def test_get_all_tools_mcp_not_initialized(self, mock_session):
        available_tools = BASIC_TOOLS[:2]
        agent_state = AgentState(mock_session, available_tools=available_tools)

        mock_mcp_manager = Mock()
        mock_mcp_manager.is_initialized.return_value = False
        agent_state.mcp_manager = mock_mcp_manager

        tools = agent_state.get_all_tools()

        assert tools == available_tools
        mock_mcp_manager.get_mcp_tools.assert_not_called()

    def test_get_all_tools_no_available_tools(self, mock_session):
        agent_state = AgentState(mock_session, available_tools=None)

        tools = agent_state.get_all_tools()

        assert tools == []

    def test_invalidate_tools_cache(self, mock_session):
        agent_state = AgentState(mock_session)
        agent_state._tools_cache_dirty = False

        agent_state.invalidate_tools_cache()

        assert agent_state._tools_cache_dirty is True

    def test_print_usage(self, mock_session):
        agent_state = AgentState(mock_session)

        with patch('klaudecode.tui.console') as mock_console:
            agent_state.print_usage()

            assert mock_console.print.call_count == 2
            mock_console.print.assert_any_call()
            mock_console.print.assert_any_call(agent_state.usage)
