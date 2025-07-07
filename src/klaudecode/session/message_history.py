from enum import Enum
from typing import Dict, List, Literal, Optional, Tuple

from pydantic import BaseModel, Field

from ..message import BasicMessage


class MessageStorageStatus(str, Enum):
    """Status of message storage in JSONL file, used exclusively for incremental updates."""

    NEW = 'new'  # Message not yet stored
    STORED = 'stored'  # Message stored in file


class MessageStorageState(BaseModel):
    """State tracking for message storage in JSONL format."""

    status: MessageStorageStatus = MessageStorageStatus.NEW
    line_number: Optional[int] = None  # Line number in JSONL file (0-based)
    file_path: Optional[str] = None  # Path to JSONL file


class MessageHistory(BaseModel):
    messages: List[BasicMessage] = Field(default_factory=list)
    storage_states: Dict[int, MessageStorageState] = Field(default_factory=dict, exclude=True)

    def append_message(self, *msgs: BasicMessage) -> None:
        start_index = len(self.messages)
        self.messages.extend(msgs)
        # Mark new messages as NEW status
        for i, _ in enumerate(msgs, start=start_index):
            self.storage_states[i] = MessageStorageState(status=MessageStorageStatus.NEW)

    def get_storage_state(self, index: int) -> MessageStorageState:
        """Get storage state for a message."""
        return self.storage_states.get(index, MessageStorageState())

    def set_storage_state(self, index: int, state: MessageStorageState) -> None:
        """Set storage state for a message."""
        self.storage_states[index] = state

    def get_unsaved_messages(self) -> List[Tuple[int, BasicMessage]]:
        """Get all messages that need to be saved (NEW)."""
        return [(i, msg) for i, msg in enumerate(self.messages) if self.storage_states.get(i, MessageStorageState()).status == MessageStorageStatus.NEW]

    def reset_storage_states(self) -> None:
        for i in range(len(self.messages)):
            self.storage_states[i] = MessageStorageState(status=MessageStorageStatus.NEW, line_number=i + 1, file_path=None)

    def get_last_message(self, role: Literal['user', 'assistant', 'tool'] | None = None, filter_empty: bool = False) -> Optional[BasicMessage]:
        return next((msg for msg in reversed(self.messages) if (not role or msg.role == role) and (not filter_empty or msg)), None)

    def get_first_message(self, role: Literal['user', 'assistant', 'tool'] | None = None, filter_empty: bool = False) -> Optional[BasicMessage]:
        return next((msg for msg in self.messages if (not role or msg.role == role) and (not filter_empty or msg)), None)

    def get_role_messages(self, role: Literal['user', 'assistant', 'tool'] | None = None, filter_empty: bool = False) -> List[BasicMessage]:
        return [msg for msg in self.messages if (not role or msg.role == role) and (not filter_empty or msg)]

    def print_all_message(self):
        from ..tui import console

        for msg in self.messages:
            if msg.role == 'system':
                continue
            if msg.role == 'assistant' and not msg.content and not msg.thinking_content:
                continue
            console.print()
            console.print(msg)
        console.print()

    def copy(self):
        return self.messages.copy()

    def extend(self, msgs):
        self.messages.extend(msgs)

    def __len__(self) -> int:
        return len(self.messages)

    def __iter__(self):
        return iter(self.messages)

    def __getitem__(self, index):
        return self.messages[index]
