from enum import Enum

BASH = "Bash"
APPLY_PATCH = "apply_patch"
EDIT = "Edit"
MULTI_EDIT = "MultiEdit"
READ = "Read"
TODO_WRITE = "TodoWrite"
UPDATE_PLAN = "update_plan"
TASK = "Task"
ORACLE = "Oracle"
SKILL = "Skill"


class SubAgentType(str, Enum):
    TASK = TASK
    ORACLE = ORACLE
