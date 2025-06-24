from typing import TYPE_CHECKING

from ..prompt.commands import INIT_COMMAND
from ..user_input import UserInput
from .rewrite_query_command import RewriteQueryCommand

if TYPE_CHECKING:
    pass


class InitCommand(RewriteQueryCommand):
    def get_name(self) -> str:
        return 'init'

    def get_command_desc(self) -> str:
        return 'Initialize a new CLAUDE.md file with codebase documentation'

    def get_query_content(self, user_input: UserInput) -> str:
        return INIT_COMMAND
