from enum import Enum

BASH = "Bash"
SHELL = "Shell"
EDIT = "Edit"
MULTI_EDIT = "MultiEdit"
READ = "Read"
TODO_WRITE = "TodoWrite"
EXIT_PLAN_MODE = "exit_plan_mode"
TASK = "Task"
ORACLE = "Oracle"


class SubAgentType(str, Enum):
    TASK = TASK
    ORACLE = ORACLE  # For now subagent type should has the same name as tool name, used in repl_display.py#pick_sub_agent_color
