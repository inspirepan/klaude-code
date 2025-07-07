import time
import uuid
import weakref
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from klaudecode.message import AIMessage, SystemMessage, UserMessage
from klaudecode.session import Session
from klaudecode.session.message_history import MessageHistory
from klaudecode.tools.todo import TodoList
from klaudecode.utils.file_utils import FileTracker


class TestSession:
    def test_session_initialization_default(self):
        work_dir = Path('/test/work/dir')
        session = Session(work_dir=work_dir)

        assert session.work_dir == work_dir
        assert isinstance(session.messages, MessageHistory)
        assert isinstance(session.todo_list, TodoList)
        assert isinstance(session.file_tracker, FileTracker)
        assert session.source == 'user'
        assert len(session.session_id) > 0
        assert session.created_at > 0
        assert session.append_message_hook is None
        assert session.title_msg == ''

    def test_session_initialization_with_messages_list(self):
        work_dir = Path('/test/work/dir')
        messages = [
            UserMessage(content='Hello'),
            AIMessage(content='Hi there')
        ]
        
        session = Session(work_dir=work_dir, messages=messages)
        
        assert isinstance(session.messages, MessageHistory)
        assert len(session.messages) == 2
        assert session.messages[0].content == 'Hello'
        assert session.messages[1].content == 'Hi there'

    def test_session_initialization_with_message_history(self):
        work_dir = Path('/test/work/dir')
        message_history = MessageHistory(messages=[
            UserMessage(content='Test message')
        ])
        
        session = Session(work_dir=work_dir, messages=message_history)
        
        assert session.messages is message_history
        assert len(session.messages) == 1

    def test_session_work_dir_serialization(self):
        work_dir = Path('/test/work/dir')
        session = Session(work_dir=work_dir)
        
        serialized = session.model_dump()
        assert serialized['work_dir'] == '/test/work/dir'

    def test_append_message(self):
        work_dir = Path('/test')
        session = Session(work_dir=work_dir)
        
        user_msg = UserMessage(content='Hello')
        ai_msg = AIMessage(content='Hi')
        
        session.append_message(user_msg, ai_msg)
        
        assert len(session.messages) == 2
        assert session.messages[0] == user_msg
        assert session.messages[1] == ai_msg

    def test_append_message_with_hook(self):
        work_dir = Path('/test')
        session = Session(work_dir=work_dir)
        
        hook_calls = []
        def test_hook(*msgs):
            hook_calls.extend(msgs)
        
        session.set_append_message_hook(test_hook)
        
        user_msg = UserMessage(content='Hello')
        session.append_message(user_msg)
        
        assert len(hook_calls) == 1
        assert hook_calls[0] == user_msg

    def test_append_message_hook_weakref_cleanup(self):
        work_dir = Path('/test')
        session = Session(work_dir=work_dir)
        
        def test_hook(*msgs):
            pass
        
        session.set_append_message_hook(test_hook)
        assert session.append_message_hook is not None
        assert session._hook_weakref is not None
        
        # Clear both the local reference and the session's strong reference
        del test_hook
        session.append_message_hook = None
        
        # Force garbage collection to clean up the weakref
        import gc
        gc.collect()
        
        # The weakref should now be dead  
        assert session._hook_weakref() is None
        
        user_msg = UserMessage(content='Hello')
        session.append_message(user_msg)
        
        # After calling append_message, the hook should be cleaned up
        assert session.append_message_hook is None
        assert session._hook_weakref is None

    def test_append_message_hook_exception_handling(self):
        work_dir = Path('/test')
        session = Session(work_dir=work_dir)
        
        def failing_hook(*msgs):
            raise ValueError('Hook failed')
        
        session.set_append_message_hook(failing_hook)
        
        with patch('logging.warning') as mock_warning:
            user_msg = UserMessage(content='Hello')
            session.append_message(user_msg)
            
            mock_warning.assert_called_once()
            assert 'Exception in append_message_hook' in str(mock_warning.call_args)

    def test_set_append_message_hook_none(self):
        work_dir = Path('/test')
        session = Session(work_dir=work_dir)
        
        def test_hook(*msgs):
            pass
        
        session.set_append_message_hook(test_hook)
        assert session.append_message_hook is not None
        
        session.set_append_message_hook(None)
        assert session.append_message_hook is None
        assert session._hook_weakref is None

    @patch('klaudecode.session.session.SessionStorage.save')
    def test_save(self, mock_save):
        work_dir = Path('/test')
        session = Session(work_dir=work_dir)
        
        session.save()
        
        mock_save.assert_called_once_with(session)

    def test_reset_create_at(self):
        work_dir = Path('/test')
        session = Session(work_dir=work_dir)
        
        original_time = session.created_at
        time.sleep(0.01)
        
        session.reset_create_at()
        
        assert session.created_at > original_time

    def test_create_session_from_template_default(self):
        work_dir = Path('/test')
        original_session = Session(work_dir=work_dir)
        original_session.append_message(UserMessage(content='Test'))
        
        new_session = original_session._create_session_from_template()
        
        assert new_session.work_dir == original_session.work_dir
        assert new_session.session_id != original_session.session_id
        assert len(new_session.messages) == 1
        assert new_session.messages[0].content == 'Test'
        assert new_session.source == 'user'

    def test_create_session_from_template_filter_removed(self):
        work_dir = Path('/test')
        original_session = Session(work_dir=work_dir)
        
        msg1 = UserMessage(content='Keep this')
        msg2 = UserMessage(content='Remove this')
        msg2.removed = True
        
        original_session.append_message(msg1, msg2)
        
        new_session = original_session._create_session_from_template(filter_removed=True)
        
        assert len(new_session.messages) == 1
        assert new_session.messages[0].content == 'Keep this'

    def test_create_session_from_template_with_source(self):
        work_dir = Path('/test')
        original_session = Session(work_dir=work_dir)
        
        new_session = original_session._create_session_from_template(source='compact')
        
        assert new_session.source == 'compact'

    def test_create_new_session(self):
        work_dir = Path('/test')
        original_session = Session(work_dir=work_dir)
        original_session.append_message(UserMessage(content='Test'))
        
        new_session = original_session.create_new_session()
        
        assert new_session.session_id != original_session.session_id
        assert len(new_session.messages) == 1

    @patch('klaudecode.session.session.SessionOperations.clear_conversation_history')
    def test_clear_conversation_history(self, mock_clear):
        work_dir = Path('/test')
        session = Session(work_dir=work_dir)
        
        session.clear_conversation_history()
        
        mock_clear.assert_called_once_with(session)

    @patch('klaudecode.session.session.SessionOperations.compact_conversation_history')
    @pytest.mark.asyncio
    async def test_compact_conversation_history(self, mock_compact):
        work_dir = Path('/test')
        session = Session(work_dir=work_dir)
        llm_manager = Mock()
        
        await session.compact_conversation_history(
            instructions='test', 
            show_status=False, 
            llm_manager=llm_manager
        )
        
        mock_compact.assert_called_once_with(
            session, 'test', False, llm_manager
        )

    @patch('klaudecode.session.session.SessionOperations.analyze_conversation_for_command')
    @pytest.mark.asyncio
    async def test_analyze_conversation_for_command(self, mock_analyze):
        work_dir = Path('/test')
        session = Session(work_dir=work_dir)
        llm_manager = Mock()
        mock_analyze.return_value = {'pattern': 'test'}
        
        result = await session.analyze_conversation_for_command(llm_manager)
        
        mock_analyze.assert_called_once_with(session, llm_manager)
        assert result == {'pattern': 'test'}

    @patch('klaudecode.session.session.SessionStorage.load')
    def test_load_class_method(self, mock_load):
        mock_session = Mock()
        mock_load.return_value = mock_session
        
        result = Session.load('test_id', Path('/test'))
        
        mock_load.assert_called_once_with('test_id', Path('/test'))
        assert result == mock_session

    @patch('klaudecode.session.session.SessionStorage.load_session_list')
    def test_load_session_list_class_method(self, mock_load_list):
        mock_sessions = [{'id': '1'}, {'id': '2'}]
        mock_load_list.return_value = mock_sessions
        
        result = Session.load_session_list(Path('/test'))
        
        mock_load_list.assert_called_once_with(Path('/test'))
        assert result == mock_sessions

    @patch('klaudecode.session.session.SessionStorage.get_latest_session')
    def test_get_latest_session_class_method(self, mock_get_latest):
        mock_session = Mock()
        mock_get_latest.return_value = mock_session
        
        result = Session.get_latest_session(Path('/test'))
        
        mock_get_latest.assert_called_once_with(Path('/test'))
        assert result == mock_session

    def test_session_fields_validation(self):
        with pytest.raises(ValueError):
            Session()

    def test_session_id_uniqueness(self):
        work_dir = Path('/test')
        session1 = Session(work_dir=work_dir)
        session2 = Session(work_dir=work_dir)
        
        assert session1.session_id != session2.session_id

    def test_session_source_validation(self):
        work_dir = Path('/test')
        
        valid_sources = ['user', 'subagent', 'clear', 'compact']
        for source in valid_sources:
            session = Session(work_dir=work_dir, source=source)
            assert session.source == source

    def test_session_with_custom_session_id(self):
        work_dir = Path('/test')
        custom_id = 'custom-session-id'
        
        session = Session(work_dir=work_dir, session_id=custom_id)
        
        assert session.session_id == custom_id

    def test_session_with_custom_created_at(self):
        work_dir = Path('/test')
        custom_time = 1234567890.0
        
        session = Session(work_dir=work_dir, created_at=custom_time)
        
        assert session.created_at == custom_time