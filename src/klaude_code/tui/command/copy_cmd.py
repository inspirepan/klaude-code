import json

from klaude_code.protocol import commands, events, message, tools
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
    """Collect the last assistant response, merging across Mermaid tool call boundaries."""
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
    segments: list[str] = [_format_assistant(last_msg)]

    # Walk backwards, merging across Mermaid-only tool calls
    saw_mermaid = False
    i = last_idx - 1
    while i >= 0:
        item = history[i]
        if isinstance(item, message.ToolResultMessage) and item.tool_name == tools.MERMAID:
            saw_mermaid = True
            i -= 1
        elif isinstance(item, message.AssistantMessage) and saw_mermaid:
            segments.append(_format_assistant(item))
            saw_mermaid = False
            i -= 1
        elif isinstance(item, (message.ToolResultMessage, message.UserMessage, message.AssistantMessage)):
            break
        else:
            i -= 1

    segments.reverse()
    return "\n\n".join(s for s in segments if s).strip()


def _format_assistant(msg: message.AssistantMessage) -> str:
    formatted = message.join_text_parts(msg.parts)

    for part in msg.parts:
        if isinstance(part, message.ToolCallPart) and part.tool_name == tools.MERMAID:
            try:
                code = json.loads(part.arguments_json).get("code", "")
            except (json.JSONDecodeError, AttributeError):
                continue
            if code:
                formatted += f"\n\n```mermaid\n{code}\n```"

    return formatted.strip()


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
