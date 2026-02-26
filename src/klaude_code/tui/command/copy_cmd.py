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

        last = _collect_assistant_text(agent.session.conversation_history)
        if not last:
            return _command_output(agent, "(no assistant message to copy)", self.name, is_error=True)

        copy_to_clipboard(last)
        return _command_output(agent, "Copied last assistant message to clipboard.", self.name)


def _collect_assistant_text(history: list[message.HistoryEvent]) -> str:
    """Collect the last assistant response."""
    # Find the last AssistantMessage
    last_idx = -1
    for i in range(len(history) - 1, -1, -1):
        if isinstance(history[i], message.AssistantMessage):
            last_idx = i
            break

    if last_idx < 0:
        return ""

    last_msg = history[last_idx]
    assert isinstance(last_msg, message.AssistantMessage)
    return _format_assistant(last_msg)


def _format_assistant(msg: message.AssistantMessage) -> str:
    return message.join_text_parts(msg.parts).strip()


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
