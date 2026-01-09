from klaude_code.protocol import commands, events, message, op

from .command_abc import Agent, CommandABC, CommandResult


class ContinueCommand(CommandABC):
    """Continue agent execution without adding a new user message."""

    @property
    def name(self) -> commands.CommandName:
        return commands.CommandName.CONTINUE

    @property
    def summary(self) -> str:
        return "Continue agent execution (for recovery after interruptions)"

    async def run(self, agent: Agent, user_input: message.UserInputPayload) -> CommandResult:
        del user_input  # unused

        if agent.session.messages_count == 0:
            return CommandResult(
                events=[
                    events.CommandOutputEvent(
                        session_id=agent.session.id,
                        command_name=self.name,
                        content="Cannot continue: no conversation history. Start a conversation first.",
                        is_error=True,
                    )
                ]
            )

        return CommandResult(
            operations=[op.ContinueAgentOperation(session_id=agent.session.id)],
        )
