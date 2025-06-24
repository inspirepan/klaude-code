from typing import TYPE_CHECKING

from ..prompt.commands import TODAY_COMMAND
from ..user_input import UserInput
from .rewrite_query_command import RewriteQueryCommand

if TYPE_CHECKING:
    pass


class TodayCommand(RewriteQueryCommand):
    def get_name(self) -> str:
        return 'today'

    def get_command_desc(self) -> str:
        return "Analyze today's development activities in this codebase through git commit history"

    def get_query_content(self, user_input: UserInput) -> str:
        return TODAY_COMMAND
