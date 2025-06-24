from typing import TYPE_CHECKING

from ..user_input import CommandHandleOutput, InputModeCommand, UserInput

if TYPE_CHECKING:
    from ..agent import Agent


class PlanMode(InputModeCommand):
    def get_name(self) -> str:
        return 'plan'

    def _get_prompt(self) -> str:
        return '*'

    def _get_color(self) -> str:
        return '#6aa4a5'

    def get_placeholder(self) -> str:
        return 'type to start planning...'

    def get_next_mode_name(self) -> str:
        return 'plan'

    def binding_key(self) -> str:
        return '*'

    async def handle(self, agent: 'Agent', user_input: UserInput) -> CommandHandleOutput:
        user_msg, _ = await super().handle(agent, user_input)
        agent.append_message(user_msg)
        agent.plan_mode_activated = True
        return CommandHandleOutput(user_msg=user_msg, need_agent_run=True)
