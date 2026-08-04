from enum import Enum


class SessionRuntimeState(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    WAITING_USER_INPUT = "waiting_user_input"


__all__ = ["SessionRuntimeState"]
