import asyncio

from klaude_code.command.command_abc import Agent, CommandABC, CommandResult
from klaude_code.protocol import commands, events, model, op
from klaude_code.session.selector import resume_select_session


class ResumeCommand(CommandABC):
    """Resume a previous session."""

    @property
    def name(self) -> commands.CommandName:
        return commands.CommandName.RESUME

    @property
    def summary(self) -> str:
        return "Resume a previous session"

    @property
    def is_interactive(self) -> bool:
        return True

    async def run(self, agent: Agent, user_input: model.UserInputPayload) -> CommandResult:
        del user_input  # unused

        if agent.session.messages_count > 0:
            event = events.DeveloperMessageEvent(
                session_id=agent.session.id,
                item=model.DeveloperMessageItem(
                    content="Cannot resume: current session already has messages. Use `klaude -r` to start a new instance with session selection.",
                    command_output=model.CommandOutput(command_name=self.name, is_error=True),
                ),
            )
            return CommandResult(events=[event], persist_user_input=False, persist_events=False)

        selected_session_id = await asyncio.to_thread(resume_select_session)
        if selected_session_id is None:
            event = events.DeveloperMessageEvent(
                session_id=agent.session.id,
                item=model.DeveloperMessageItem(
                    content="(no session selected)",
                    command_output=model.CommandOutput(command_name=self.name),
                ),
            )
            return CommandResult(events=[event], persist_user_input=False, persist_events=False)

        return CommandResult(
            operations=[op.ResumeSessionOperation(target_session_id=selected_session_id)],
            persist_user_input=False,
            persist_events=False,
        )
