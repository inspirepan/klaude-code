import uuid
from pathlib import Path

from pydantic import BaseModel

from src.protocal import ResponseItem


class Session(BaseModel):
    id: str = uuid.uuid4().hex
    work_dir: Path
    conversation_history: list[ResponseItem] = []

    @classmethod
    def load(cls, id: str) -> "Session":
        # TODO
        print(id)
        return Session(work_dir=Path.cwd())

    def save(self):
        pass
