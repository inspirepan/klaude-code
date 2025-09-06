import uuid
from collections.abc import Sequence
from pathlib import Path

from pydantic import BaseModel, Field

from codex_mini.protocol.model import ConversationItem


class Session(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    work_dir: Path
    conversation_history: list[ConversationItem] = Field(default_factory=list)
    system_prompt: str | None = None
    last_response_id: str | None = None

    @classmethod
    def load(cls, id: str) -> "Session":
        # TODO
        return Session(id=id, work_dir=Path.cwd())

    def save(self):
        # TODO
        pass

    def append_history(self, items: Sequence[ConversationItem]):
        self.conversation_history.extend(items)
