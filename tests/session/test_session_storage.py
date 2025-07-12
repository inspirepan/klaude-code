import json
import tempfile
import time
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from klaudecode.message import AIMessage, SystemMessage, ToolMessage, UserMessage
from klaudecode.session import Session
from klaudecode.session.message_history import MessageStorageStatus
from klaudecode.session.session_storage import SessionStorage


class TestSessionStorage:
    def setup_method(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name)
        self.work_dir = self.temp_path / 'test_work'
        self.work_dir.mkdir(parents=True, exist_ok=True)

    def teardown_method(self):
        self.temp_dir.cleanup()

    def test_get_session_dir(self):
        session_dir = SessionStorage.get_session_dir(self.work_dir)

        expected = self.work_dir / '.klaude' / 'sessions'
        assert session_dir == expected

    def test_get_formatted_filename_prefix_user_source(self):
        session = Session(work_dir=self.work_dir)
        session.created_at = 1234567890.0  # Known timestamp
        session.title_msg = 'test session title'

        prefix = SessionStorage.get_formatted_filename_prefix(session)

        dt = datetime.fromtimestamp(1234567890.0)
        expected_datetime = dt.strftime('%Y_%m%d_%H%M%S')
        assert prefix.startswith(expected_datetime)
        assert 'test_session_title' in prefix

    def test_get_formatted_filename_prefix_subagent_source(self):
        session = Session(work_dir=self.work_dir, source='subagent')
        session.created_at = 1234567890.0
        session.title_msg = 'subagent test'

        prefix = SessionStorage.get_formatted_filename_prefix(session)

        assert '.SUBAGENT' in prefix
        assert 'subagent_test' in prefix

    def test_get_formatted_filename_prefix_clear_source(self):
        session = Session(work_dir=self.work_dir, source='clear')
        session.created_at = 1234567890.0
        session.title_msg = 'cleared session'

        prefix = SessionStorage.get_formatted_filename_prefix(session)

        assert '.CLEAR' in prefix

    def test_get_formatted_filename_prefix_compact_source(self):
        session = Session(work_dir=self.work_dir, source='compact')
        session.created_at = 1234567890.0
        session.title_msg = 'compacted session'

        prefix = SessionStorage.get_formatted_filename_prefix(session)

        assert '.COMPACT' in prefix

    def test_get_metadata_file_path(self):
        session = Session(work_dir=self.work_dir)
        session.title_msg = 'test'

        metadata_path = SessionStorage.get_metadata_file_path(session)

        assert metadata_path.parent == SessionStorage.get_session_dir(self.work_dir)
        assert '.metadata.' in metadata_path.name
        assert metadata_path.name.endswith('.json')
        assert session.session_id in metadata_path.name

    def test_get_messages_file_path(self):
        session = Session(work_dir=self.work_dir)
        session.title_msg = 'test'

        messages_path = SessionStorage.get_messages_file_path(session)

        assert messages_path.parent == SessionStorage.get_session_dir(self.work_dir)
        assert '.messages.' in messages_path.name
        assert messages_path.name.endswith('.jsonl')
        assert session.session_id in messages_path.name

    def test_save_session_without_user_messages(self):
        session = Session(work_dir=self.work_dir)
        session.append_message(SystemMessage(content='System message'))

        SessionStorage.save(session)

        session_dir = SessionStorage.get_session_dir(self.work_dir)
        assert not session_dir.exists() or len(list(session_dir.glob('*'))) == 0

    def test_save_session_with_user_messages(self):
        session = Session(work_dir=self.work_dir)
        session.append_message(UserMessage(content='Hello', user_raw_input='Hello'), AIMessage(content='Hi there'))

        SessionStorage.save(session)

        session_dir = SessionStorage.get_session_dir(self.work_dir)
        assert session_dir.exists()

        metadata_files = list(session_dir.glob('*.metadata.*.json'))
        messages_files = list(session_dir.glob('*.messages.*.jsonl'))

        assert len(metadata_files) == 1
        assert len(messages_files) == 1

    def test_save_session_auto_title_generation(self):
        session = Session(work_dir=self.work_dir)
        session.append_message(UserMessage(content='This is my question', user_raw_input='This is my question'))
        session.append_message(AIMessage(content='This is the answer'))

        SessionStorage.save(session)

        assert session.title_msg == 'This is my question'

    def test_save_session_metadata_content(self):
        session = Session(work_dir=self.work_dir)
        session.append_message(UserMessage(content='Test', user_raw_input='Test'))
        session.title_msg = 'Test Session'

        SessionStorage.save(session)

        metadata_file = SessionStorage.get_metadata_file_path(session)

        with open(metadata_file, 'r', encoding='utf-8') as f:
            metadata = json.load(f)

        assert metadata['id'] == session.session_id
        assert metadata['work_dir'] == str(session.work_dir)
        assert metadata['created_at'] == session.created_at
        assert 'updated_at' in metadata
        assert metadata['message_count'] == 1
        assert metadata['source'] == 'user'
        assert metadata['title_msg'] == 'Test Session'

    def test_save_session_messages_jsonl_new_file(self):
        session = Session(work_dir=self.work_dir)
        user_msg = UserMessage(content='Hello', user_raw_input='Hello')
        ai_msg = AIMessage(content='Hi there')
        session.append_message(user_msg, ai_msg)

        SessionStorage.save(session)

        messages_file = SessionStorage.get_messages_file_path(session)

        with open(messages_file, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        assert len(lines) == 3  # Header + 2 messages

        header = json.loads(lines[0])
        assert header['session_id'] == session.session_id
        assert header['version'] == '1.0'

        msg1_data = json.loads(lines[1])
        assert msg1_data['content'] == 'Hello'
        assert msg1_data['role'] == 'user'

        msg2_data = json.loads(lines[2])
        assert msg2_data['content'] == 'Hi there'
        assert msg2_data['role'] == 'assistant'

    def test_save_session_incremental_updates(self):
        session = Session(work_dir=self.work_dir)
        user_msg1 = UserMessage(content='First message', user_raw_input='First message')
        session.append_message(user_msg1)

        SessionStorage.save(session)

        user_msg2 = UserMessage(content='Second message', user_raw_input='Second message')
        session.append_message(user_msg2)

        SessionStorage.save(session)

        messages_file = SessionStorage.get_messages_file_path(session)

        with open(messages_file, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        assert len(lines) == 3  # Header + 2 messages

        msg2_data = json.loads(lines[2])
        assert msg2_data['content'] == 'Second message'

    def test_save_session_storage_state_updates(self):
        session = Session(work_dir=self.work_dir)
        user_msg = UserMessage(content='Test', user_raw_input='Test')
        session.append_message(user_msg)

        assert session.messages.get_storage_state(0).status == MessageStorageStatus.NEW

        SessionStorage.save(session)

        state = session.messages.get_storage_state(0)
        assert state.status == MessageStorageStatus.STORED
        assert state.line_number == 1  # First message after header

    @patch('klaudecode.session.session_storage.console.print')
    def test_save_session_exception_handling(self, mock_print):
        session = Session(work_dir=Path('/nonexistent/path'))
        session.append_message(UserMessage(content='Test', user_raw_input='Test'))

        SessionStorage.save(session)

        mock_print.assert_called_once()
        assert 'Failed to save session' in str(mock_print.call_args)

    def test_load_session_nonexistent(self):
        result = SessionStorage.load('nonexistent-id', self.work_dir)

        assert result is None

    def test_load_session_success(self):
        # First create a session
        original_session = Session(work_dir=self.work_dir)
        original_session.append_message(UserMessage(content='Hello', user_raw_input='Hello'), AIMessage(content='Hi there'))
        original_session.title_msg = 'Test Session'

        SessionStorage.save(original_session)

        # Now load it
        loaded_session = SessionStorage.load(original_session.session_id, self.work_dir)

        assert loaded_session is not None
        assert loaded_session.session_id == original_session.session_id
        assert loaded_session.work_dir == original_session.work_dir
        assert loaded_session.title_msg == original_session.title_msg
        assert len(loaded_session.messages) == 2
        assert loaded_session.messages[0].content == 'Hello'
        assert loaded_session.messages[1].content == 'Hi there'

    def test_load_session_with_tool_messages(self):
        original_session = Session(work_dir=self.work_dir)

        # Create AI message with tool call
        from klaudecode.message.tool_call import ToolCall

        ai_msg = AIMessage(content='Using tool')
        tool_call = ToolCall(id='call_123', tool_name='test_tool', tool_args_dict={'arg': 'value'})
        ai_msg.tool_calls = {'call_123': tool_call}

        tool_msg = ToolMessage(content='Tool result', tool_call_id='call_123', tool_call_cache=tool_call)

        original_session.append_message(UserMessage(content='Test', user_raw_input='Test'), ai_msg, tool_msg)

        SessionStorage.save(original_session)

        loaded_session = SessionStorage.load(original_session.session_id, self.work_dir)

        assert loaded_session is not None
        assert len(loaded_session.messages) == 3

    def test_load_session_with_corrupted_message_line(self):
        session = Session(work_dir=self.work_dir)
        session.append_message(UserMessage(content='Test', user_raw_input='Test'))

        SessionStorage.save(session)

        # Corrupt the messages file
        messages_file = SessionStorage.get_messages_file_path(session)
        with open(messages_file, 'a', encoding='utf-8') as f:
            f.write('invalid json line\n')

        with patch('klaudecode.session.session_storage.console.print') as mock_print:
            loaded_session = SessionStorage.load(session.session_id, self.work_dir)

            assert loaded_session is not None
            assert len(loaded_session.messages) == 1  # Only valid message loaded
            mock_print.assert_called()

    def test_load_session_exception_handling(self):
        # Create fake files so the method proceeds to the open call
        session_dir = SessionStorage.get_session_dir(self.work_dir)
        session_dir.mkdir(parents=True, exist_ok=True)

        fake_metadata = session_dir / 'fake.metadata.test-id.json'
        fake_messages = session_dir / 'fake.messages.test-id.jsonl'
        fake_metadata.touch()
        fake_messages.touch()

        with patch('klaudecode.session.session_storage.console.print') as mock_print:
            with patch('builtins.open', side_effect=Exception('File error')):
                result = SessionStorage.load('test-id', self.work_dir)

                assert result is None
                mock_print.assert_called_once()
                assert 'Failed to load session' in str(mock_print.call_args)

    def test_load_session_list_empty_directory(self):
        sessions = SessionStorage.load_session_list(self.work_dir)

        assert sessions == []

    def test_load_session_list_with_sessions(self):
        # Create multiple sessions
        session1 = Session(work_dir=self.work_dir)
        session1.append_message(UserMessage(content='First', user_raw_input='First'))
        session1.title_msg = 'First Session'

        session2 = Session(work_dir=self.work_dir)
        session2.append_message(UserMessage(content='Second', user_raw_input='Second'))
        session2.title_msg = 'Second Session'

        # Save with different timestamps
        session1.created_at = 1000.0
        session2.created_at = 2000.0

        SessionStorage.save(session1)
        SessionStorage.save(session2)

        sessions = SessionStorage.load_session_list(self.work_dir)

        assert len(sessions) == 2
        # Should be sorted by updated_at in descending order
        assert sessions[0]['title_msg'] == 'Second Session'
        assert sessions[1]['title_msg'] == 'First Session'

    def test_load_session_list_excludes_subagent(self):
        # Create regular session
        session1 = Session(work_dir=self.work_dir, source='user')
        session1.append_message(UserMessage(content='User session', user_raw_input='User session'))

        # Create subagent session
        session2 = Session(work_dir=self.work_dir, source='subagent')
        session2.append_message(UserMessage(content='Subagent session', user_raw_input='Subagent session'))

        SessionStorage.save(session1)
        SessionStorage.save(session2)

        sessions = SessionStorage.load_session_list(self.work_dir)

        assert len(sessions) == 1
        assert sessions[0]['source'] == 'user'

    @patch('klaudecode.session.session_storage.console.print')
    def test_load_session_list_corrupted_metadata(self, mock_print):
        # Create session directory with corrupted metadata file
        session_dir = SessionStorage.get_session_dir(self.work_dir)
        session_dir.mkdir(parents=True, exist_ok=True)

        corrupted_file = session_dir / 'corrupted.metadata.test-id.json'
        corrupted_file.write_text('invalid json', encoding='utf-8')

        sessions = SessionStorage.load_session_list(self.work_dir)

        assert sessions == []
        mock_print.assert_called()

    def test_load_session_list_exception_handling(self):
        with patch('klaudecode.session.session_storage.console.print') as mock_print:
            with patch('klaudecode.session.session_storage.SessionStorage.get_session_dir', side_effect=Exception('Dir error')):
                sessions = SessionStorage.load_session_list(self.work_dir)

                assert sessions == []
                mock_print.assert_called_once()
                assert 'Failed to list sessions' in str(mock_print.call_args)

    def test_get_latest_session_no_sessions(self):
        result = SessionStorage.get_latest_session(self.work_dir)

        assert result is None

    def test_get_latest_session_success(self):
        # Create multiple sessions
        session1 = Session(work_dir=self.work_dir)
        session1.append_message(UserMessage(content='First', user_raw_input='First'))
        session1.created_at = 1000.0

        session2 = Session(work_dir=self.work_dir)
        session2.append_message(UserMessage(content='Second', user_raw_input='Second'))
        session2.created_at = 2000.0

        SessionStorage.save(session1)
        time.sleep(0.01)  # Ensure different updated_at times
        SessionStorage.save(session2)

        latest_session = SessionStorage.get_latest_session(self.work_dir)

        assert latest_session is not None
        assert latest_session.session_id == session2.session_id

    def test_save_messages_jsonl_with_existing_storage_states(self):
        session = Session(work_dir=self.work_dir)

        # Add first message and save
        msg1 = UserMessage(content='First', user_raw_input='First')
        session.append_message(msg1)
        SessionStorage.save(session)

        # Verify storage state is set
        state1 = session.messages.get_storage_state(0)
        assert state1.status == MessageStorageStatus.STORED

        # Add second message
        msg2 = UserMessage(content='Second', user_raw_input='Second')
        session.append_message(msg2)

        # Verify only new message is unsaved
        unsaved = session.messages.get_unsaved_messages()
        assert len(unsaved) == 1
        assert unsaved[0][1] == msg2

        SessionStorage.save(session)

        # Verify both messages are now stored
        state2 = session.messages.get_storage_state(1)
        assert state2.status == MessageStorageStatus.STORED
