from .bash_input_mode import BashMode
from .clear_command import ClearCommand
from .compact_command import CompactCommand
from .continue_command import ContinueCommand
from .cost_command import CostCommand
from .init_command import InitCommand
from .mac_setup_command import MacSetupCommand
from .memory_input_mode import MemoryMode
from .plan_input_mode import PlanMode
from .recent_command import RecentCommand
from .rewrite_query_command import RewriteQueryCommand
from .status_command import StatusCommand
from .theme_command import ThemeCommand
from .today_command import TodayCommand

__all__ = [
    'StatusCommand',
    'ContinueCommand',
    'CompactCommand',
    'CostCommand',
    'ClearCommand',
    'MacSetupCommand',
    'RewriteQueryCommand',
    'InitCommand',
    'TodayCommand',
    'RecentCommand',
    'ThemeCommand',
    'PlanMode',
    'BashMode',
    'MemoryMode',
]

from ..user_input import register_input_mode, register_slash_command

register_input_mode(PlanMode())
register_input_mode(BashMode())
register_input_mode(MemoryMode())
register_slash_command(StatusCommand())
register_slash_command(InitCommand())
register_slash_command(ClearCommand())
register_slash_command(CompactCommand())
register_slash_command(TodayCommand())
register_slash_command(RecentCommand())
register_slash_command(ContinueCommand())
# register_slash_command(CostCommand())
register_slash_command(MacSetupCommand())
register_slash_command(ThemeCommand())
