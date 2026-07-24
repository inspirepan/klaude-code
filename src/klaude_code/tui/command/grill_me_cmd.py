from klaude_code.prompts.grilling import GRILLING_PROMPT
from klaude_code.protocol import message, op
from klaude_code.tui.command.command_abc import Agent, CommandABC, CommandResult
from klaude_code.tui.command.types import CommandName


class GrillMeCommand(CommandABC):
    """Stress-test a plan, decision, or idea through an interactive interview."""

    @property
    def name(self) -> CommandName:
        return CommandName.GRILL_ME

    @property
    def summary(self) -> str:
        return "Stress-test a plan, decision, or idea through relentless questions"

    @property
    def support_addition_params(self) -> bool:
        return True

    @property
    def placeholder(self) -> str:
        return "plan, decision, or idea"

    async def run(self, agent: Agent, user_input: message.UserInputPayload) -> CommandResult:
        topic = user_input.text.strip()
        prompt = GRILLING_PROMPT
        if topic:
            prompt = f"{prompt}\n\nTopic to grill me about:\n{topic}"

        return CommandResult(
            operations=[
                op.RunAgentOperation(
                    session_id=agent.session.id,
                    input=message.UserInputPayload(text=prompt, images=user_input.images),
                )
            ]
        )
