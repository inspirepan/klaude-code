from klaude_code.protocol import commands, message, op
from klaude_code.tui.command.command_abc import Agent, CommandABC, CommandResult


class CompactCommand(CommandABC):
    @property
    def name(self) -> commands.CommandName:
        return commands.CommandName.COMPACT

    @property
    def summary(self) -> str:
        return "Clear conversation history but keep a summary in context"

    @property
    def support_addition_params(self) -> bool:
        return True

    @property
    def placeholder(self) -> str:
        return "instructions"

    async def run(self, agent: Agent, user_input: message.UserInputPayload) -> CommandResult:
        focus = user_input.text.strip() if user_input.text else None
        return CommandResult(
            operations=[
                op.CompactSessionOperation(
                    session_id=agent.session.id,
                    reason="manual",
                    focus=focus or None,
                )
            ]
        )
