import uuid
from collections.abc import Sequence
from pathlib import Path

from pydantic import BaseModel, Field

from src.protocol import ResponseItem


class Session(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    work_dir: Path
    conversation_history: list[ResponseItem] = Field(default_factory=list)
    system_prompt: str = Field(default_factory=str)
    last_response_id: str | None = None

    @classmethod
    def load(cls, id: str) -> "Session":
        return Session(id=id, work_dir=Path.cwd())

    def save(self):
        pass

    def append_history(self, items: Sequence[ResponseItem]):
        self.conversation_history.extend(items)
