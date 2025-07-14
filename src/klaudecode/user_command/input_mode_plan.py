from ..agent import AgentState
from ..tui import ColorStyle, get_prompt_toolkit_color
from ..user_input import CommandHandleOutput, InputModeCommand, UserInput


class PlanMode(InputModeCommand):
    def get_name(self) -> str:
        return 'plan'

    def _get_prompt(self) -> str:
        return '*'

    def _get_color(self) -> str:
        return get_prompt_toolkit_color(ColorStyle.PLAN_MODE)

    def _get_placeholder(self) -> str:
        return 'Plan mode on...'

    def binding_key(self) -> str:
        return '*'

    async def handle(self, agent_state: 'AgentState', user_input: UserInput) -> CommandHandleOutput:
        command_handle_output = await super().handle(agent_state, user_input)
        agent_state.plan_mode_activated = True
        return command_handle_output
