from enum import Enum


class CommandName(str, Enum):
    INIT = "init"
    DIFF = "diff"
    HELP = "help"
    MODEL = "model"
    COMPACT = "compact"
    REFRESH_TERMINAL = "refresh-terminal"
    CLEAR = "clear"
    TERMINAL_SETUP = "terminal-setup"
    EXPORT = "export"
    STATUS = "status"
    # PLAN and DOC are dynamically registered now, but kept here if needed for reference
    # or we can remove them if no code explicitly imports them.
    # PLAN = "plan"
    # DOC = "doc"

    def __str__(self) -> str:
        return self.value
