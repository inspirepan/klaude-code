from klaude_code.protocol import message, op
from klaude_code.tui.command.command_abc import Agent, CommandABC, CommandResult
from klaude_code.tui.command.types import CommandName


class StopCommand(CommandABC):
    @property
    def name(self) -> CommandName:
        return CommandName.STOP

    @property
    def summary(self) -> str:
        return "Stop this session's child agents (not the root, Bash, or peers)"

    @property
    def runs_in_background(self) -> bool:
        return True

    async def run(self, agent: Agent, user_input: message.UserInputPayload) -> CommandResult:
        return CommandResult(operations=[op.StopSubAgentsOperation(session_id=agent.session.id)])
