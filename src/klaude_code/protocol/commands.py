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
    HELP = "help"
    MODEL = "model"
    COMPACT = "compact"
    REFRESH_TERMINAL = "refresh-terminal"
    CLEAR = "clear"
    TERMINAL_SETUP = "terminal-setup"
    EXPORT = "export"
    EXPORT_ONLINE = "export-online"
    STATUS = "status"
    RELEASE_NOTES = "release-notes"
    THINKING = "thinking"
    FORK_SESSION = "fork-session"
    RESUME = "resume"
    # PLAN and DOC are dynamically registered now, but kept here if needed for reference
    # or we can remove them if no code explicitly imports them.
    # PLAN = "plan"
    # DOC = "doc"

    def __str__(self) -> str:
        return self.value
