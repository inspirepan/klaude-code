from typing import TYPE_CHECKING

from ..prompt.commands import RECENT_COMMAND
from ..user_input import UserInput
from .rewrite_query_command import RewriteQueryCommand

if TYPE_CHECKING:
    pass


class RecentCommand(RewriteQueryCommand):
    def get_name(self) -> str:
        return 'recent'

    def get_command_desc(self) -> str:
        return 'Analyze recent development activities in this codebase through current branch commit history'

    def get_query_content(self, user_input: UserInput) -> str:
        return RECENT_COMMAND
