from enum import Enum

from pydantic import BaseModel

from klaude_code.protocol.models.common import RuntimeKind


class SessionRuntimeState(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    WAITING_USER_INPUT = "waiting_user_input"


class SessionOwner(BaseModel):
    runtime_id: str
    runtime_kind: RuntimeKind
    pid: int


__all__ = ["SessionOwner", "SessionRuntimeState"]
