from klaude_code.protocol import events, message
from klaude_code.tui.input.key_bindings import copy_to_clipboard

from .command_abc import Agent, CommandABC, CommandResult
from .types import CommandName


class CopyCommand(CommandABC):
    """Copy an assistant message to system clipboard."""

    @property
    def name(self) -> CommandName:
        return CommandName.COPY

    @property
    def summary(self) -> str:
        return "Copy last response to clipboard (or /copy N for the Nth-latest)"

    @property
    def support_addition_params(self) -> bool:
        return True

    @property
    def placeholder(self) -> str:
        return "N"

    async def run(self, agent: Agent, user_input: message.UserInputPayload) -> CommandResult:
        arg = user_input.text.strip()
        n = 1
        if arg:
            try:
                n = int(arg)
            except ValueError:
                return _command_output(
                    agent, f"Invalid /copy argument: {arg!r} (expected a positive integer).", is_error=True
                )
            if n < 1:
                return _command_output(
                    agent, f"Invalid /copy argument: {n} (expected a positive integer).", is_error=True
                )

        text = _collect_assistant_text(agent.session.conversation_history, n)
        if not text:
            suffix = "" if n == 1 else f" (only {_count_assistant(agent.session.conversation_history)} available)"
            return _command_output(agent, f"(no assistant message to copy{suffix})", is_error=True)

        copy_to_clipboard(text)
        label = "last assistant message" if n == 1 else f"assistant message #{n} from the end"
        return _command_output(agent, f"Copied {label} to clipboard.")

def _collect_assistant_text(history: list[message.HistoryEvent], n: int) -> str:
    """Collect the Nth-latest assistant response (n=1 is the most recent)."""
    seen = 0
    for i in range(len(history) - 1, -1, -1):
        msg = history[i]
        if isinstance(msg, message.AssistantMessage):
            seen += 1
            if seen == n:
                return _format_assistant(msg)
    return ""

def _count_assistant(history: list[message.HistoryEvent]) -> int:
    return sum(1 for m in history if isinstance(m, message.AssistantMessage))

def _format_assistant(msg: message.AssistantMessage) -> str:
    return message.join_text_parts(msg.parts).strip()

def _command_output(agent: Agent, content: str, *, is_error: bool = False) -> CommandResult:
    return CommandResult(
        events=[
            events.NoticeEvent(
                session_id=agent.session.id,
                content=content,
                is_error=is_error,
            )
        ],
    )
