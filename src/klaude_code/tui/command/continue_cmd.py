from klaude_code.protocol import events, message, op

from .command_abc import Agent, CommandABC, CommandResult
from .types import CommandName


class ContinueCommand(CommandABC):
    """Continue agent execution without adding a new user message."""

    @property
    def name(self) -> CommandName:
        return CommandName.CONTINUE

    @property
    def summary(self) -> str:
        return "Continue current session without a new user message"

    async def run(self, agent: Agent, user_input: message.UserInputPayload) -> CommandResult:
        del user_input  # unused

        if agent.session.messages_count == 0:
            return CommandResult(
                events=[
                    events.NoticeEvent(
                        session_id=agent.session.id,
                        content="Cannot continue: no conversation history. Start a conversation first.",
                        is_error=True,
                    )
                ]
            )

        return CommandResult(
            operations=[op.ContinueAgentOperation(session_id=agent.session.id)],
        )
