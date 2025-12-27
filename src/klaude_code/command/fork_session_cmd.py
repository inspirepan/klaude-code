from klaude_code.command.command_abc import Agent, CommandABC, CommandResult
from klaude_code.protocol import commands, events, model


class ForkSessionCommand(CommandABC):
    """Fork current session to a new session id and show a resume command."""

    @property
    def name(self) -> commands.CommandName:
        return commands.CommandName.FORK_SESSION

    @property
    def summary(self) -> str:
        return "Fork the current session and show a resume-by-id command"

    async def run(self, agent: Agent, user_input: model.UserInputPayload) -> CommandResult:
        del user_input  # unused

        if agent.session.messages_count == 0:
            event = events.DeveloperMessageEvent(
                session_id=agent.session.id,
                item=model.DeveloperMessageItem(
                    content="(no messages to fork)",
                    command_output=model.CommandOutput(command_name=self.name),
                ),
            )
            return CommandResult(events=[event], persist_user_input=False, persist_events=False)

        new_session = agent.session.fork()
        await new_session.wait_for_flush()

        event = events.DeveloperMessageEvent(
            session_id=agent.session.id,
            item=model.DeveloperMessageItem(
                content=f"Session forked successfully. New session id: {new_session.id}",
                command_output=model.CommandOutput(
                    command_name=self.name,
                    ui_extra=model.SessionIdUIExtra(session_id=new_session.id),
                ),
            ),
        )
        return CommandResult(events=[event], persist_user_input=False, persist_events=False)
