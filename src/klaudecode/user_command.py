from typing import TYPE_CHECKING, Generator, Tuple
from abc import ABC, abstractmethod

from rich.abc import RichRenderable

from .config import ConfigModel
from .message import UserMessage
from .tui import render_suffix
from .user_input import NORMAL_MODE_NAME, Command, InputModeCommand, UserInput, register_input_mode, register_slash_command
from .prompt.commands import TODAY_COMMAND, RECENT_COMMAND, INIT_COMMAND, COMPACT_COMMAND

if TYPE_CHECKING:
    from .agent import Agent
"""
This file is the concrete implementation of `Command` and `InputModeCommand` ABC in `user_input.py`
"""


# Commands
# ---------------------

## Special Commands
# ---------------------


class StatusCommand(Command):
    def get_name(self) -> str:
        return 'status'

    def get_command_desc(self) -> str:
        return 'Show the current setup'

    def handle(self, agent: 'Agent', user_input: UserInput) -> Tuple[UserMessage, bool]:
        user_msg, _ = super().handle(agent, user_input)
        user_msg.set_extra_data('status', agent.config)
        return user_msg, False

    def render_user_msg_suffix(self, user_msg: UserMessage) -> Generator[RichRenderable, None, None]:
        config_data = user_msg.get_extra_data('status')
        if config_data:
            if isinstance(config_data, ConfigModel):
                config_model = config_data
            elif isinstance(config_data, dict):
                config_model = ConfigModel.model_validate(config_data)
            else:
                return
            yield render_suffix(config_model)


class ContinueCommand(Command):
    def get_name(self) -> str:
        return 'continue'

    def get_command_desc(self) -> str:
        return 'Request LLM without new user message. NOTE: May cause error when no user message exists'

    def handle(self, agent: 'Agent', user_input: UserInput) -> Tuple[UserMessage, bool]:
        user_msg, _ = super().handle(agent, user_input)
        return user_msg, True


class CompactCommand(Command):
    def get_name(self) -> str:
        return 'compact'

    def get_command_desc(self) -> str:
        return 'Clear conversation history but keep a summary in context. Optional: /compact [instructions for summarization]'

    # TODO: Implement


class CostCommand(Command):
    def get_name(self) -> str:
        return 'cost'

    def get_command_desc(self) -> str:
        return 'Show the total cost and duration of the current session'

    # TODO: Implement


class ClearCommand(Command):
    def get_name(self) -> str:
        return 'clear'

    def get_command_desc(self) -> str:
        return 'Clear conversation history and free up context'

    # TODO: Implement


## Rewrite Query Commands
# ---------------------


class RewriteQueryCommand(Command, ABC):
    @abstractmethod
    def get_query_content(self) -> str:
        pass

    def handle(self, agent: 'Agent', user_input: UserInput) -> Tuple[UserMessage, bool]:
        user_msg, _ = super().handle(agent, user_input)
        user_msg.content = self.get_query_content()
        if user_input.cleaned_input:
            user_msg.content += f'\n<requirement>\n{user_input.cleaned_input}\n</requirement>'
        return user_msg, True


class InitCommand(RewriteQueryCommand):
    def get_name(self) -> str:
        return 'init'

    def get_command_desc(self) -> str:
        return 'Initialize a new CLAUDE.md file with codebase documentation'

    def get_query_content(self) -> str:
        return INIT_COMMAND


class TodayCommand(RewriteQueryCommand):
    def get_name(self) -> str:
        return 'today'

    def get_command_desc(self) -> str:
        return "Analyze today's development activities in this codebase through git commit history"

    def get_query_content(self) -> str:
        return TODAY_COMMAND


class RecentCommand(RewriteQueryCommand):
    def get_name(self) -> str:
        return 'recent'

    def get_command_desc(self) -> str:
        return 'Analyze recent development activities in this codebase through current branch commit history'

    def get_query_content(self) -> str:
        return RECENT_COMMAND


register_slash_command(StatusCommand())
register_slash_command(ContinueCommand())
register_slash_command(CompactCommand())
register_slash_command(InitCommand())
register_slash_command(CostCommand())
register_slash_command(ClearCommand())
register_slash_command(TodayCommand())
register_slash_command(RecentCommand())

# Input Modes
# ---------------------


class PlanMode(InputModeCommand):
    def get_name(self) -> str:
        return 'plan'

    def _get_prompt(self) -> str:
        return '*'

    def _get_color(self) -> str:
        return '#6aa4a5'

    def get_placeholder(self) -> str:
        return 'type plan...'

    def get_next_mode_name(self) -> str:
        return 'plan'

    def binding_key(self) -> str:
        return '*'

    # TODO: Implement handle


class BashMode(InputModeCommand):
    def get_name(self) -> str:
        return 'bash'

    def _get_prompt(self) -> str:
        return '!'

    def _get_color(self) -> str:
        return '#ea3386'

    def get_placeholder(self) -> str:
        return 'type command...'

    def get_next_mode_name(self) -> str:
        return NORMAL_MODE_NAME

    def binding_key(self) -> str:
        return '!'

    # TODO: Implement handle


class MemoryMode(InputModeCommand):
    def get_name(self) -> str:
        return 'memory'

    def _get_prompt(self) -> str:
        return '#'

    def _get_color(self) -> str:
        return '#b3b9f4'

    def get_placeholder(self) -> str:
        return 'type memory...'

    def get_next_mode_name(self) -> str:
        return NORMAL_MODE_NAME

    def binding_key(self) -> str:
        return '#'

    # TODO: Implement handle


register_input_mode(PlanMode())
register_input_mode(BashMode())
register_input_mode(MemoryMode())
