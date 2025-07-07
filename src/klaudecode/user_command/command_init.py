from ..prompt.commands import INIT_COMMAND
from ..user_input import UserInput
from .query_rewrite_command import QueryRewriteCommand


class InitCommand(QueryRewriteCommand):
    def get_name(self) -> str:
        return 'init'

    def get_command_desc(self) -> str:
        return 'Initialize a new CLAUDE.md file with codebase documentation'

    def get_query_content(self, user_input: UserInput) -> str:
        return INIT_COMMAND
