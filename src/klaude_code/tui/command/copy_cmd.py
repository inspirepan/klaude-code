from klaude_code.protocol import commands, events, message
from klaude_code.tui.input.key_bindings import copy_to_clipboard

from .command_abc import Agent, CommandABC, CommandResult


class CopyCommand(CommandABC):
    """Copy the last assistant message to system clipboard."""

    @property
    def name(self) -> commands.CommandName:
        return commands.CommandName.COPY

    @property
    def summary(self) -> str:
        return "Copy last assistant message to clipboard"

    async def run(self, agent: Agent, user_input: message.UserInputPayload) -> CommandResult:
        del user_input  # unused

        last = _get_last_assistant_text(agent.session.conversation_history)
        if not last:
            return _command_output(agent, "(no assistant message to copy)", self.name, is_error=True)

        copy_to_clipboard(last)
        return _command_output(agent, "Copied last assistant message to clipboard.", self.name)


def _get_last_assistant_text(history: list[message.HistoryEvent]) -> str:
    for item in reversed(history):
        if not isinstance(item, message.AssistantMessage):
            continue
        content = message.join_text_parts(item.parts)
        images = [part for part in item.parts if isinstance(part, message.ImageFilePart)]
        formatted = message.format_saved_images(images, content)
        return formatted.strip()
    return ""


def _command_output(
    agent: Agent, content: str, command_name: commands.CommandName, *, is_error: bool = False
) -> CommandResult:
    return CommandResult(
        events=[
            events.CommandOutputEvent(
                session_id=agent.session.id,
                command_name=command_name,
                content=content,
                is_error=is_error,
            )
        ],
    )
