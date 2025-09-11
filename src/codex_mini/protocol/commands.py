from enum import Enum


class CommandName(str, Enum):
    INIT = "init"
    DIFF = "diff"
    HELP = "help"
    MODEL = "model"
    COMPACT = "compact"
    PLAN = "plan"
    REFRESH_TERMINAL = "refresh-terminal"
    CLEAR = "clear"
    TERMINAL_SETUP = "terminal-setup"

    def __str__(self) -> str:
        return self.value
