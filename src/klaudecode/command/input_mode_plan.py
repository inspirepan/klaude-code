from typing import TYPE_CHECKING

from ..tui import ColorStyle, get_prompt_toolkit_color
from ..user_input import CommandHandleOutput, InputModeCommand, UserInput

if TYPE_CHECKING:
    from ..agent import Agent


class PlanMode(InputModeCommand):
    def get_name(self) -> str:
        return 'plan'

    def _get_prompt(self) -> str:
        return '*'

    def _get_color(self) -> str:
        return get_prompt_toolkit_color(ColorStyle.PLAN_MODE)

    def _get_placeholder(self) -> str:
        return 'plan mode on...'

    def get_next_mode_name(self) -> str:
        return 'plan'

    def binding_key(self) -> str:
        return '*'

    async def handle(self, agent: 'Agent', user_input: UserInput) -> CommandHandleOutput:
        command_handle_output = await super().handle(agent, user_input)
        agent.plan_mode_activated = True
        command_handle_output.need_agent_run = True
        return command_handle_output
