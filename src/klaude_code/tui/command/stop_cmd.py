from klaude_code.protocol import message, op
from klaude_code.tui.command.command_abc import Agent, CommandABC, CommandResult
from klaude_code.tui.command.types import CommandName


class StopCommand(CommandABC):
    @property
    def name(self) -> CommandName:
        return CommandName.STOP

    @property
    def summary(self) -> str:
        return "Stop all tasks in this session, including owned agents and Bash (not peers)"

    @property
    def runs_in_background(self) -> bool:
        return True

    async def run(self, agent: Agent, user_input: message.UserInputPayload) -> CommandResult:
        return CommandResult(operations=[op.StopAllTasksOperation(session_id=agent.session.id)])
