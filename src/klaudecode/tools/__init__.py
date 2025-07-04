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
from .undo_edit import UndoEditTool
from .write import WriteTool

# Tool collections

BASIC_TOOLS = [BashTool, GlobTool, GrepTool, LsTool, ExitPlanModeTool, ReadTool, EditTool, MultiEditTool, WriteTool, UndoEditTool, TodoReadTool, TodoWriteTool]
READ_ONLY_TOOLS = [GlobTool, GrepTool, LsTool, ReadTool, TodoWriteTool, TodoReadTool]

__all__ = [
    'BashTool',
    'TodoReadTool',
    'TodoWriteTool',
    'EditTool',
    'ExitPlanModeTool',
    'MultiEditTool',
    'ReadTool',
    'UndoEditTool',
    'WriteTool',
    'LsTool',
    'GrepTool',
    'GlobTool',
    'BASIC_TOOLS',
    'READ_ONLY_TOOLS',
]
