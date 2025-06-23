from typing import List, Literal, Optional

from pydantic import BaseModel, Field

from .message import BasicMessage


class MessageHistory(BaseModel):
    messages: List[BasicMessage] = Field(default_factory=list)

    def append_message(self, *msgs: BasicMessage) -> None:
        self.messages.extend(msgs)

    def get_last_message(self, role: Literal['user', 'assistant', 'tool'] | None = None, filter_empty: bool = False) -> Optional[BasicMessage]:
        return next((msg for msg in reversed(self.messages) if (not role or msg.role == role) and (not filter_empty or msg)), None)

    def get_first_message(self, role: Literal['user', 'assistant', 'tool'] | None = None, filter_empty: bool = False) -> Optional[BasicMessage]:
        return next((msg for msg in self.messages if (not role or msg.role == role) and (not filter_empty or msg)), None)

    def print_all_message(self):
        from .tui import console

        for msg in self.messages:
            console.print(msg)

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
