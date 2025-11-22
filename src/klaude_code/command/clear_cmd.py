from klaude_code.command.command_abc import CommandABC, CommandResult
from klaude_code.command.registry import register_command
from klaude_code.core import Agent
from klaude_code.protocol.commands import CommandName
from klaude_code.protocol.events import DeveloperMessageEvent
from klaude_code.protocol.model import CommandOutput, DeveloperMessageItem
from klaude_code.session.session import Session


@register_command
class ClearCommand(CommandABC):
    """Clear current session and start a new conversation"""

    @property
    def name(self) -> CommandName:
        return CommandName.CLEAR

    @property
    def summary(self) -> str:
        return "Clear conversation history and free up context"

    async def run(self, raw: str, agent: Agent) -> CommandResult:
        # Create a new session instance to replace the current one
        new_session = Session(work_dir=agent.session.work_dir)
        new_session.model_name = agent.session.model_name

        # Replace the agent's session with the new one
        agent.session = new_session

        # Save the new session
        agent.session.save()

        return CommandResult(
            events=[
                DeveloperMessageEvent(
                    session_id=agent.session.id,
                    item=DeveloperMessageItem(
                        content="started new conversation",
                        command_output=CommandOutput(command_name=self.name),
                    ),
                ),
            ]
        )
