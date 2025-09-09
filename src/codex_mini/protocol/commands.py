from enum import Enum


class CommandName(str, Enum):
    INIT = "init"
    DIFF = "diff"
    HELP = "help"
    MODEL = "model"
    COMPACT = "compact"
    PLAN = "plan"

    def __str__(self) -> str:
        return self.value
