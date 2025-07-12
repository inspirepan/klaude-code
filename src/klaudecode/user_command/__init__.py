from .command_clear import ClearCommand
from .command_compact import CompactCommand
from .command_continue import ContinueCommand
from .command_cost import CostCommand
from .command_debug import DebugCommand
from .command_example_custom_command import ExampleCustomCommand
from .command_init import InitCommand
from .command_mac_setup import MacSetupCommand
from .command_mcp import MCPCommand
from .command_memory import MemoryCommand
from .command_output import OutputCommand
from .command_save_custom_command import SaveCustomCommandCommand
from .command_status import StatusCommand
from .command_theme import ThemeCommand
from .custom_command import CustomCommand
from .custom_command_manager import CustomCommandManager, custom_command_manager
from .input_mode_bash import BashMode
from .input_mode_memory import MemoryMode
from .input_mode_plan import PlanMode
from .query_rewrite_command import QueryRewriteCommand

__all__ = [
    'StatusCommand',
    'ContinueCommand',
    'CompactCommand',
    'CostCommand',
    'ClearCommand',
    'DebugCommand',
    'MacSetupCommand',
    'MCPCommand',
    'QueryRewriteCommand',
    'MemoryCommand',
    'InitCommand',
    'OutputCommand',
    'ThemeCommand',
    'ExampleCustomCommand',
    'SaveCustomCommandCommand',
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
register_slash_command(OutputCommand())
register_slash_command(CompactCommand())
register_slash_command(MemoryCommand())
register_slash_command(DebugCommand())
register_slash_command(MCPCommand())
register_slash_command(ClearCommand())
register_slash_command(ContinueCommand())
register_slash_command(CostCommand())
register_slash_command(ThemeCommand())
if MacSetupCommand.need_mac_setup():
    register_slash_command(MacSetupCommand())
if not ExampleCustomCommand.already_has_custom_command():
    register_slash_command(ExampleCustomCommand())
register_slash_command(SaveCustomCommandCommand())
