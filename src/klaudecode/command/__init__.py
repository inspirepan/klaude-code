from .bash_input_mode import BashMode
from .clear_command import ClearCommand
from .compact_command import CompactCommand
from .continue_command import ContinueCommand
from .cost_command import CostCommand
from .create_example_command import CreateExampleCommand
from .custom_command import CustomCommand
from .custom_command_manager import CustomCommandManager, custom_command_manager
from .init_command import InitCommand
from .mac_setup_command import MacSetupCommand
from .memory_input_mode import MemoryMode
from .plan_input_mode import PlanMode
from .rewrite_query_command import RewriteQueryCommand
from .save_as_custom_command import SaveAsCustomCommandCommand
from .status_command import StatusCommand
from .theme_command import ThemeCommand

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
