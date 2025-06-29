from .input_mode_bash import BashMode
from .command_clear import ClearCommand
from .command_compact import CompactCommand
from .command_continue import ContinueCommand
from .command_cost import CostCommand
from .command_create_example_custom_command import CreateExampleCommand
from .custom_command import CustomCommand
from .custom_command_manager import CustomCommandManager, custom_command_manager
from .command_init import InitCommand
from .command_mac_setup import MacSetupCommand
from .input_mode_memory import MemoryMode
from .input_mode_plan import PlanMode
from .rewrite_query_command import RewriteQueryCommand
from .command_save_as_custom_command import SaveAsCustomCommandCommand
from .command_status import StatusCommand
from .command_theme import ThemeCommand

__all__ = [
    'StatusCommand',
    'ContinueCommand',
    'CompactCommand',
    'CostCommand',
    'ClearCommand',
    'MacSetupCommand',
    'RewriteQueryCommand',
    'InitCommand',
    'ThemeCommand',
    'CreateExampleCommand',
    'SaveAsCustomCommandCommand',
    'PlanMode',
    'BashMode',
    'MemoryMode',
    'CustomCommand',
    'CustomCommandManager',
    'custom_command_manager',
]

from ..user_input import register_input_mode, register_slash_command

register_input_mode(PlanMode())
register_input_mode(BashMode())
register_input_mode(MemoryMode())
register_slash_command(StatusCommand())
register_slash_command(InitCommand())
register_slash_command(ClearCommand())
register_slash_command(CompactCommand())
register_slash_command(ContinueCommand())
# register_slash_command(CostCommand())
register_slash_command(MacSetupCommand())
register_slash_command(ThemeCommand())
register_slash_command(CreateExampleCommand())
register_slash_command(SaveAsCustomCommandCommand())
