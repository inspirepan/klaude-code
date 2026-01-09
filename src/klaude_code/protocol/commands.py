from dataclasses import dataclass
from enum import Enum


@dataclass(frozen=True, slots=True)
class CommandInfo:
    """Lightweight command metadata for UI purposes (no logic)."""

    name: str
    summary: str
    support_addition_params: bool = False
    placeholder: str = ""


class CommandName(str, Enum):
    INIT = "init"
    DEBUG = "debug"
    MODEL = "model"
    SUB_AGENT_MODEL = "sub-agent-model"
    COMPACT = "compact"
    REFRESH_TERMINAL = "refresh-terminal"
    CLEAR = "clear"
    EXPORT = "export"
    EXPORT_ONLINE = "export-online"
    STATUS = "status"
    THINKING = "thinking"
    FORK_SESSION = "fork-session"
    RESUME = "resume"
    COPY = "copy"
    CONTINUE = "continue"

    def __str__(self) -> str:
        return self.value
