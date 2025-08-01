import pytest

from klaudecode.message import AIMessage, SystemMessage, UserMessage
from klaudecode.session.message_history import (
    MessageHistory,
    MessageStorageState,
    MessageStorageStatus,
)


class TestMessageStorageState:
    def test_default_values(self):
        state = MessageStorageState()

        assert state.status == MessageStorageStatus.NEW
        assert state.line_number is None
        assert state.file_path is None

    def test_custom_values(self):
        state = MessageStorageState(
            status=MessageStorageStatus.STORED,
            line_number=5,
            file_path="/test/file.jsonl",
        )

        assert state.status == MessageStorageStatus.STORED
        assert state.line_number == 5
        assert state.file_path == "/test/file.jsonl"


class TestMessageHistory:
    def test_initialization_empty(self):
        history = MessageHistory()

        assert len(history.messages) == 0
        assert len(history.storage_states) == 0

    def test_initialization_with_messages(self):
        messages = [UserMessage(content="Hello"), AIMessage(content="Hi there")]

        history = MessageHistory(messages=messages)

        assert len(history.messages) == 2
        assert history.messages[0].content == "Hello"
        assert history.messages[1].content == "Hi there"

    def test_append_message_single(self):
        history = MessageHistory()
        msg = UserMessage(content="Test message")

        history.append_message(msg)

        assert len(history.messages) == 1
        assert history.messages[0] == msg
        assert history.storage_states[0].status == MessageStorageStatus.NEW

    def test_append_message_multiple(self):
        history = MessageHistory()
        msg1 = UserMessage(content="First")
        msg2 = AIMessage(content="Second")
        msg3 = UserMessage(content="Third")

        history.append_message(msg1, msg2, msg3)

        assert len(history.messages) == 3
        assert history.messages[0] == msg1
        assert history.messages[1] == msg2
        assert history.messages[2] == msg3

        for i in range(3):
            assert history.storage_states[i].status == MessageStorageStatus.NEW

    def test_append_message_incremental(self):
        history = MessageHistory()

        msg1 = UserMessage(content="First")
        history.append_message(msg1)

        msg2 = AIMessage(content="Second")
        history.append_message(msg2)

        assert len(history.messages) == 2
        assert history.storage_states[0].status == MessageStorageStatus.NEW
        assert history.storage_states[1].status == MessageStorageStatus.NEW

    def test_get_storage_state_existing(self):
        history = MessageHistory()
        msg = UserMessage(content="Test")
        history.append_message(msg)

        state = history.get_storage_state(0)

        assert state.status == MessageStorageStatus.NEW

    def test_get_storage_state_non_existing(self):
        history = MessageHistory()

        state = history.get_storage_state(5)

        assert state.status == MessageStorageStatus.NEW
        assert state.line_number is None

    def test_set_storage_state(self):
        history = MessageHistory()
        msg = UserMessage(content="Test")
        history.append_message(msg)

        new_state = MessageStorageState(
            status=MessageStorageStatus.STORED,
            line_number=10,
            file_path="/test/file.jsonl",
        )

        history.set_storage_state(0, new_state)

        retrieved_state = history.get_storage_state(0)
        assert retrieved_state.status == MessageStorageStatus.STORED
        assert retrieved_state.line_number == 10
        assert retrieved_state.file_path == "/test/file.jsonl"

    def test_get_unsaved_messages_empty(self):
        history = MessageHistory()

        unsaved = history.get_unsaved_messages()

        assert len(unsaved) == 0

    def test_get_unsaved_messages_all_new(self):
        history = MessageHistory()
        msg1 = UserMessage(content="First")
        msg2 = AIMessage(content="Second")
        history.append_message(msg1, msg2)

        unsaved = history.get_unsaved_messages()

        assert len(unsaved) == 2
        assert unsaved[0] == (0, msg1)
        assert unsaved[1] == (1, msg2)

    def test_get_unsaved_messages_mixed(self):
        history = MessageHistory()
        msg1 = UserMessage(content="First")
        msg2 = AIMessage(content="Second")
        msg3 = UserMessage(content="Third")
        history.append_message(msg1, msg2, msg3)

        # Mark middle message as stored
        stored_state = MessageStorageState(status=MessageStorageStatus.STORED)
        history.set_storage_state(1, stored_state)

        unsaved = history.get_unsaved_messages()

        assert len(unsaved) == 2
        assert unsaved[0] == (0, msg1)
        assert unsaved[1] == (2, msg3)

    def test_reset_storage_states(self):
        history = MessageHistory()
        msg1 = UserMessage(content="First")
        msg2 = AIMessage(content="Second")
        history.append_message(msg1, msg2)

        # Mark as stored
        stored_state = MessageStorageState(status=MessageStorageStatus.STORED)
        history.set_storage_state(0, stored_state)
        history.set_storage_state(1, stored_state)

        history.reset_storage_states()

        assert history.storage_states[0].status == MessageStorageStatus.NEW
        assert history.storage_states[0].line_number == 1
        assert history.storage_states[1].status == MessageStorageStatus.NEW
        assert history.storage_states[1].line_number == 2

    def test_get_last_message_no_filter(self):
        history = MessageHistory()
        msg1 = UserMessage(content="First")
        msg2 = AIMessage(content="Second")
        msg3 = SystemMessage(content="Third")
        history.append_message(msg1, msg2, msg3)

        last_msg = history.get_last_message()

        assert last_msg == msg3

    def test_get_last_message_with_role_filter(self):
        history = MessageHistory()
        msg1 = UserMessage(content="First")
        msg2 = AIMessage(content="Second")
        msg3 = UserMessage(content="Third")
        history.append_message(msg1, msg2, msg3)

        last_user_msg = history.get_last_message(role="user")

        assert last_user_msg == msg3

    def test_get_last_message_with_empty_filter(self):
        history = MessageHistory()
        msg1 = UserMessage(content="First")
        msg2 = AIMessage(content="")  # Empty message
        msg3 = UserMessage(content="Third")
        history.append_message(msg1, msg2, msg3)

        last_non_empty = history.get_last_message(filter_empty=True)

        assert last_non_empty == msg3

    def test_get_last_message_no_match(self):
        history = MessageHistory()
        msg1 = UserMessage(content="First")
        history.append_message(msg1)

        last_tool_msg = history.get_last_message(role="tool")

        assert last_tool_msg is None

    def test_get_first_message_no_filter(self):
        history = MessageHistory()
        msg1 = UserMessage(content="First")
        msg2 = AIMessage(content="Second")
        history.append_message(msg1, msg2)

        first_msg = history.get_first_message()

        assert first_msg == msg1

    def test_get_first_message_with_role_filter(self):
        history = MessageHistory()
        msg1 = SystemMessage(content="System")
        msg2 = UserMessage(content="User")
        msg3 = AIMessage(content="AI")
        history.append_message(msg1, msg2, msg3)

        first_user_msg = history.get_first_message(role="user")

        assert first_user_msg == msg2

    def test_get_first_message_no_match(self):
        history = MessageHistory()
        msg1 = UserMessage(content="First")
        history.append_message(msg1)

        first_tool_msg = history.get_first_message(role="tool")

        assert first_tool_msg is None

    def test_get_role_messages_all_roles(self):
        history = MessageHistory()
        msg1 = UserMessage(content="User1")
        msg2 = AIMessage(content="AI1")
        msg3 = UserMessage(content="User2")
        msg4 = SystemMessage(content="System1")
        history.append_message(msg1, msg2, msg3, msg4)

        all_messages = history.get_role_messages()

        assert len(all_messages) == 4

    def test_get_role_messages_specific_role(self):
        history = MessageHistory()
        msg1 = UserMessage(content="User1")
        msg2 = AIMessage(content="AI1")
        msg3 = UserMessage(content="User2")
        history.append_message(msg1, msg2, msg3)

        user_messages = history.get_role_messages(role="user")

        assert len(user_messages) == 2
        assert user_messages[0] == msg1
        assert user_messages[1] == msg3

    def test_get_role_messages_with_empty_filter(self):
        history = MessageHistory()
        msg1 = UserMessage(content="User1")
        msg2 = UserMessage(content="")  # Empty
        msg3 = UserMessage(content="User3")
        history.append_message(msg1, msg2, msg3)

        non_empty_user_messages = history.get_role_messages(
            role="user", filter_empty=True
        )

        assert len(non_empty_user_messages) == 2
        assert non_empty_user_messages[0] == msg1
        assert non_empty_user_messages[1] == msg3

    def test_copy(self):
        history = MessageHistory()
        msg1 = UserMessage(content="First")
        msg2 = AIMessage(content="Second")
        history.append_message(msg1, msg2)

        copied_messages = history.copy()

        assert len(copied_messages) == 2
        assert copied_messages[0] == msg1
        assert copied_messages[1] == msg2

    def test_extend(self):
        history = MessageHistory()
        msg1 = UserMessage(content="First")
        history.append_message(msg1)

        new_messages = [AIMessage(content="Second"), UserMessage(content="Third")]

        history.extend(new_messages)

        assert len(history.messages) == 3
        assert history.messages[1] == new_messages[0]
        assert history.messages[2] == new_messages[1]

    def test_len(self):
        history = MessageHistory()
        assert len(history) == 0

        msg1 = UserMessage(content="First")
        history.append_message(msg1)
        assert len(history) == 1

        msg2 = AIMessage(content="Second")
        history.append_message(msg2)
        assert len(history) == 2

    def test_iter(self):
        history = MessageHistory()
        msg1 = UserMessage(content="First")
        msg2 = AIMessage(content="Second")
        history.append_message(msg1, msg2)

        messages_list = list(history)

        assert len(messages_list) == 2
        assert messages_list[0] == msg1
        assert messages_list[1] == msg2

    def test_getitem(self):
        history = MessageHistory()
        msg1 = UserMessage(content="First")
        msg2 = AIMessage(content="Second")
        history.append_message(msg1, msg2)

        assert history[0] == msg1
        assert history[1] == msg2

        with pytest.raises(IndexError):
            _ = history[5]

    def test_getitem_slice(self):
        history = MessageHistory()
        messages = [
            UserMessage(content="First"),
            AIMessage(content="Second"),
            UserMessage(content="Third"),
        ]
        history.append_message(*messages)

        sliced = history[1:3]

        assert len(sliced) == 2
        assert sliced[0] == messages[1]
        assert sliced[1] == messages[2]
