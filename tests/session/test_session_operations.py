import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest

from klaudecode.message import AIMessage, SpecialUserMessageTypeEnum, SystemMessage, UserMessage
from klaudecode.session import Session
from klaudecode.session.message_history import MessageHistory
from klaudecode.session.session_operations import SessionOperations


class TestSessionOperations:
    def test_clear_conversation_history(self):
        work_dir = Path('/test')
        session = Session(work_dir=work_dir)
        
        # Add various messages
        system_msg = SystemMessage(content='System message')
        user_msg = UserMessage(content='User message')
        ai_msg = AIMessage(content='AI message')
        
        session.append_message(system_msg, user_msg, ai_msg)
        
        original_session_id = session.session_id
        original_created_at = session.created_at
        
        with patch('klaudecode.session.session_storage.SessionStorage.save') as mock_save:
            SessionOperations.clear_conversation_history(session)
            
            # Verify old session was saved
            mock_save.assert_called_once()
            
            # Verify non-system messages were marked as removed
            assert not system_msg.removed  # System messages should not be marked
            assert user_msg.removed
            assert ai_msg.removed
            
            # Verify session was updated with new data
            assert session.session_id != original_session_id
            assert session.created_at != original_created_at
            assert session.source == 'clear'
            
            # Verify only system messages remain
            assert len(session.messages) == 1
            assert session.messages[0] == system_msg

    @pytest.mark.asyncio
    async def test_compact_conversation_history_success(self):
        work_dir = Path('/test')
        session = Session(work_dir=work_dir)
        
        # Add messages
        system_msg = SystemMessage(content='System message')
        user_msg = UserMessage(content='User message')
        ai_msg = AIMessage(content='AI message')
        
        session.append_message(system_msg, user_msg, ai_msg)
        
        # Mock LLM manager
        llm_manager = Mock()
        mock_ai_response = AIMessage(content='Compacted conversation summary')
        llm_manager.call = AsyncMock(return_value=mock_ai_response)
        
        original_session_id = session.session_id
        
        with patch('klaudecode.session.session_operations.console.print') as mock_print:
            await SessionOperations.compact_conversation_history(
                session, 
                instructions='test instructions',
                show_status=True,
                llm_manager=llm_manager
            )
            
            # Verify LLM was called with correct parameters
            llm_manager.call.assert_called_once()
            call_args = llm_manager.call.call_args
            
            # Check the messages passed to LLM
            msgs = call_args.kwargs['msgs']
            assert isinstance(msgs, MessageHistory)
            assert len(msgs) >= 3  # System prompt + original messages + compact command
            
            # Verify session was updated
            assert session.session_id != original_session_id
            assert session.source == 'compact'
            
            # Verify compact result was printed
            mock_print.assert_called()

    @pytest.mark.asyncio
    async def test_compact_conversation_history_no_llm_manager(self):
        work_dir = Path('/test')
        session = Session(work_dir=work_dir)
        session.append_message(UserMessage(content='Test'))
        
        with pytest.raises(RuntimeError, match='LLM manager not initialized'):
            await SessionOperations.compact_conversation_history(session, llm_manager=None)

    @pytest.mark.asyncio
    async def test_compact_conversation_history_keyboard_interrupt(self):
        work_dir = Path('/test')
        session = Session(work_dir=work_dir)
        session.append_message(UserMessage(content='Test'))
        
        llm_manager = Mock()
        llm_manager.call = AsyncMock(side_effect=KeyboardInterrupt())
        
        # Should not raise exception
        await SessionOperations.compact_conversation_history(session, llm_manager=llm_manager)

    @pytest.mark.asyncio
    async def test_compact_conversation_history_cancelled_error(self):
        work_dir = Path('/test')
        session = Session(work_dir=work_dir)
        session.append_message(UserMessage(content='Test'))
        
        llm_manager = Mock()
        llm_manager.call = AsyncMock(side_effect=asyncio.CancelledError())
        
        # Should not raise exception
        await SessionOperations.compact_conversation_history(session, llm_manager=llm_manager)

    @pytest.mark.asyncio
    async def test_compact_conversation_history_with_additional_instructions(self):
        work_dir = Path('/test')
        session = Session(work_dir=work_dir)
        session.append_message(UserMessage(content='Test message'))
        
        llm_manager = Mock()
        mock_ai_response = AIMessage(content='Summary')
        llm_manager.call = AsyncMock(return_value=mock_ai_response)
        
        await SessionOperations.compact_conversation_history(
            session,
            instructions='Please focus on technical details',
            llm_manager=llm_manager
        )
        
        # Verify instructions were included in the compact command
        call_args = llm_manager.call.call_args
        msgs = call_args.kwargs['msgs']
        last_user_msg = None
        for msg in msgs:
            if msg.role == 'user':
                last_user_msg = msg
        
        assert last_user_msg is not None
        assert 'Please focus on technical details' in last_user_msg.content

    @pytest.mark.asyncio
    async def test_analyze_conversation_for_command_success(self):
        work_dir = Path('/test')
        session = Session(work_dir=work_dir)
        
        # Add conversation messages
        user_msg = UserMessage(content='Create a test file')
        ai_msg = AIMessage(content='I will create a test file for you')
        session.append_message(user_msg, ai_msg)
        
        # Mock LLM manager with tool call response
        llm_manager = Mock()
        from klaudecode.message.tool_call import ToolCall
        mock_tool_call = ToolCall(
            id='call_123',
            tool_name='CommandPatternResult',
            tool_args_dict={
                'command_name': 'create_test_file',
                'description': 'Creates a test file',
                'content': 'create test file $ARGUMENTS'
            }
        )
        
        mock_ai_response = AIMessage(content='Analysis complete')
        mock_ai_response.tool_calls = {'call_123': mock_tool_call}
        
        llm_manager.call = AsyncMock(return_value=mock_ai_response)
        
        result = await SessionOperations.analyze_conversation_for_command(session, llm_manager)
        
        # Verify result
        assert result is not None
        assert result['command_name'] == 'create_test_file'
        assert result['description'] == 'Creates a test file'
        assert result['content'] == 'create test file $ARGUMENTS'
        
        # Verify LLM was called correctly
        llm_manager.call.assert_called_once()
        call_args = llm_manager.call.call_args
        
        # Check that tools were passed
        assert 'tools' in call_args.kwargs
        tools = call_args.kwargs['tools']
        assert len(tools) == 1

    @pytest.mark.asyncio
    async def test_analyze_conversation_for_command_no_tool_calls(self):
        work_dir = Path('/test')
        session = Session(work_dir=work_dir)
        session.append_message(UserMessage(content='Test'))
        
        llm_manager = Mock()
        mock_ai_response = AIMessage(content='No pattern found')
        mock_ai_response.tool_calls = {}  # No tool calls
        
        llm_manager.call = AsyncMock(return_value=mock_ai_response)
        
        with patch('klaudecode.session.session_operations.console.print') as mock_print:
            result = await SessionOperations.analyze_conversation_for_command(session, llm_manager)
            
            assert result is None
            mock_print.assert_called_once()
            assert 'No tool call found' in str(mock_print.call_args)

    @pytest.mark.asyncio
    async def test_analyze_conversation_for_command_wrong_tool_name(self):
        work_dir = Path('/test')
        session = Session(work_dir=work_dir)
        session.append_message(UserMessage(content='Test'))
        
        llm_manager = Mock()
        mock_tool_call = Mock()
        mock_tool_call.tool_name = 'WrongToolName'  # Wrong tool name
        
        mock_ai_response = AIMessage(content='Analysis complete')
        mock_ai_response.tool_calls = {'call_123': mock_tool_call}
        
        llm_manager.call = AsyncMock(return_value=mock_ai_response)
        
        with patch('klaudecode.session.session_operations.console.print') as mock_print:
            result = await SessionOperations.analyze_conversation_for_command(session, llm_manager)
            
            assert result is None
            mock_print.assert_called_once()

    @pytest.mark.asyncio
    async def test_analyze_conversation_for_command_no_llm_manager(self):
        work_dir = Path('/test')
        session = Session(work_dir=work_dir)
        session.append_message(UserMessage(content='Test'))
        
        with pytest.raises(RuntimeError, match='LLM manager not initialized'):
            await SessionOperations.analyze_conversation_for_command(session, llm_manager=None)

    @pytest.mark.asyncio
    async def test_analyze_conversation_for_command_keyboard_interrupt(self):
        work_dir = Path('/test')
        session = Session(work_dir=work_dir)
        session.append_message(UserMessage(content='Test'))
        
        llm_manager = Mock()
        llm_manager.call = AsyncMock(side_effect=KeyboardInterrupt())
        
        result = await SessionOperations.analyze_conversation_for_command(session, llm_manager)
        
        assert result is None

    @pytest.mark.asyncio
    async def test_analyze_conversation_for_command_cancelled_error(self):
        work_dir = Path('/test')
        session = Session(work_dir=work_dir)
        session.append_message(UserMessage(content='Test'))
        
        llm_manager = Mock()
        llm_manager.call = AsyncMock(side_effect=asyncio.CancelledError())
        
        result = await SessionOperations.analyze_conversation_for_command(session, llm_manager)
        
        assert result is None

    @pytest.mark.asyncio
    async def test_analyze_conversation_only_non_system_messages(self):
        work_dir = Path('/test')
        session = Session(work_dir=work_dir)
        
        # Add system and non-system messages
        system_msg = SystemMessage(content='System message')
        user_msg = UserMessage(content='User message')
        ai_msg = AIMessage(content='AI message')
        
        session.append_message(system_msg, user_msg, ai_msg)
        
        llm_manager = Mock()
        mock_tool_call = Mock()
        mock_tool_call.tool_name = 'CommandPatternResultTool'
        mock_tool_call.tool_args_dict = {'pattern': 'test'}
        
        mock_ai_response = AIMessage(content='Analysis')
        mock_ai_response.tool_calls = {'call_123': mock_tool_call}
        
        llm_manager.call = AsyncMock(return_value=mock_ai_response)
        
        await SessionOperations.analyze_conversation_for_command(session, llm_manager)
        
        # Verify only non-system messages were included
        call_args = llm_manager.call.call_args
        msgs = call_args.kwargs['msgs']
        
        # Should have: system prompt + non-system messages + analyze command
        non_system_count = 2  # user_msg and ai_msg
        expected_total = 1 + non_system_count + 1  # system prompt + messages + command
        assert len(msgs) == expected_total
        
        # Verify no original system messages in the analysis
        for msg in msgs.messages[1:-1]:  # Skip system prompt and command
            assert msg.role != 'system' or msg.content != 'System message'

    def test_clear_conversation_history_preserves_system_messages(self):
        work_dir = Path('/test')
        session = Session(work_dir=work_dir)
        
        # Add multiple system messages
        system_msg1 = SystemMessage(content='System message 1')
        system_msg2 = SystemMessage(content='System message 2')
        user_msg = UserMessage(content='User message')
        
        session.append_message(system_msg1, user_msg, system_msg2)
        
        with patch('klaudecode.session.session_storage.SessionStorage.save'):
            SessionOperations.clear_conversation_history(session)
            
            # Verify both system messages are preserved
            assert len(session.messages) == 2
            assert session.messages[0] == system_msg1
            assert session.messages[1] == system_msg2
            assert not system_msg1.removed
            assert not system_msg2.removed
            assert user_msg.removed

    @pytest.mark.asyncio
    async def test_compact_conversation_history_message_types(self):
        work_dir = Path('/test')
        session = Session(work_dir=work_dir)
        
        user_msg = UserMessage(content='User message')
        ai_msg = AIMessage(content='AI message')
        session.append_message(user_msg, ai_msg)
        
        llm_manager = Mock()
        mock_ai_response = AIMessage(content='Summary')
        llm_manager.call = AsyncMock(return_value=mock_ai_response)
        
        with patch('klaudecode.session.session_operations.console.print') as mock_print:
            await SessionOperations.compact_conversation_history(session, llm_manager=llm_manager)
            
            # Verify the compact result message was created correctly
            print_calls = [call for call in mock_print.call_args_list]
            assert len(print_calls) == 1
            
            # The printed message should be a UserMessage with COMPACT_RESULT type
            printed_msg = print_calls[0][0][0]
            assert isinstance(printed_msg, UserMessage)
            assert printed_msg.user_msg_type == SpecialUserMessageTypeEnum.COMPACT_RESULT.value