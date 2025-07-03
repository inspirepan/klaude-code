"""KLAUDE-CODE - AI Agent CLI Tool"""

__version__ = '0.1.0'

from .bash import BashTool
from .edit import EditTool
from .exit_plan_mode import ExitPlanModeTool
from .glob import GlobTool
from .grep import GrepTool
from .ls import LsTool
from .multi_edit import MultiEditTool
from .read import ReadTool
from .todo import TodoReadTool, TodoWriteTool
from .write import WriteTool

# Tool collections
BASIC_TOOLS = [LsTool, GrepTool, GlobTool, ReadTool, EditTool, MultiEditTool, WriteTool, BashTool, TodoWriteTool, TodoReadTool, ExitPlanModeTool]
READ_ONLY_TOOLS = [LsTool, GrepTool, GlobTool, ReadTool, TodoWriteTool, TodoReadTool]

__all__ = [
    'BashTool',
    'TodoReadTool',
    'TodoWriteTool',
    'EditTool',
    'ExitPlanModeTool',
    'MultiEditTool',
    'ReadTool',
    'WriteTool',
    'LsTool',
    'GrepTool',
    'GlobTool',
    'BASIC_TOOLS',
    'READ_ONLY_TOOLS',
]
