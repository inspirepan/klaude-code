import asyncio
import shutil
from collections.abc import Sequence

from prompt_toolkit.utils import get_cwidth

from klaude_code.protocol import events, message
from klaude_code.tui.input.key_bindings import copy_to_clipboard
from klaude_code.tui.terminal.selector import DEFAULT_PICKER_STYLE, SelectItem, select_one

from .command_abc import Agent, CommandABC, CommandResult
from .types import CommandName

COPY_RESPONSE_LENGTH_THRESHOLD = 200


class CopyCommand(CommandABC):
    """Copy a response to the system clipboard."""

    @property
    def name(self) -> CommandName:
        return CommandName.COPY

    @property
    def summary(self) -> str:
        return "Select a response to copy (or /copy N for the Nth-latest assistant response)"

    @property
    def is_interactive(self) -> bool:
        return True

    @property
    def support_addition_params(self) -> bool:
        return True

    @property
    def placeholder(self) -> str:
        return "N"

    async def run(self, agent: Agent, user_input: message.UserInputPayload) -> CommandResult:
        arg = user_input.text.strip()
        if not arg:
            items = _build_copy_items(agent.session.conversation_history)
            if not items:
                return _command_output(
                    agent,
                    f"(no response longer than {COPY_RESPONSE_LENGTH_THRESHOLD} characters to copy)",
                    is_error=True,
                )
            selected = await asyncio.to_thread(_select_copy_entry_sync, items)
            if selected is None:
                return _command_output(agent, "(copy cancelled)")
            entry = agent.session.conversation_history[selected]
            copy_to_clipboard(_format_copyable_entry(entry))
            label = "btw answer" if isinstance(entry, message.SideQuestionEntry) else "assistant message"
            return _command_output(agent, f"Copied selected {label} to clipboard.")

        try:
            n = int(arg)
        except ValueError:
            return _command_output(
                agent, f"Invalid /copy argument: {arg!r} (expected a positive integer).", is_error=True
            )
        if n < 1:
            return _command_output(agent, f"Invalid /copy argument: {n} (expected a positive integer).", is_error=True)

        text = _collect_assistant_text(agent.session.conversation_history, n)
        if not text:
            suffix = f" (only {_count_assistant(agent.session.conversation_history)} available)"
            return _command_output(agent, f"(no assistant message to copy{suffix})", is_error=True)

        copy_to_clipboard(text)
        label = "last assistant message" if n == 1 else f"assistant message #{n} from the end"
        return _command_output(agent, f"Copied {label} to clipboard.")


def _build_copy_items(history: Sequence[message.HistoryEvent]) -> list[SelectItem[int]]:
    entries = [
        (history_index, text, isinstance(history[history_index], message.SideQuestionEntry))
        for history_index in range(len(history) - 1, -1, -1)
        if len(text := _format_copyable_entry(history[history_index])) > COPY_RESPONSE_LENGTH_THRESHOLD
    ]
    number_width = len(str(len(entries)))
    preview_width = max(20, min(100, shutil.get_terminal_size().columns - number_width - 8))
    items: list[SelectItem[int]] = []
    for position, (history_index, text, is_btw) in enumerate(entries, 1):
        first_line, second_line = _preview_lines(text, preview_width)
        continuation_indent = " " * (number_width + 2)
        content_style = "class:msg class:accent.magenta" if is_btw else "class:msg"
        title = [
            ("class:meta", f"{position:>{number_width}}. "),
            (content_style, f"{first_line}\n"),
        ]
        if second_line:
            title.extend(
                [
                    (content_style, continuation_indent),
                    (content_style, f"{second_line}\n"),
                ]
            )
        title.append((content_style, "\n"))
        items.append(
            SelectItem(
                title=title,
                value=history_index,
                search_text=text,
            )
        )
    return items


def _select_copy_entry_sync(items: list[SelectItem[int]]) -> int | None:
    try:
        return select_one(
            message=f"Select a response to copy ({len(items)}):",
            items=items,
            pointer="→",
            style=DEFAULT_PICKER_STYLE(),
            initial_value=items[0].value,
        )
    except KeyboardInterrupt:
        return None


def _format_copyable_entry(entry: message.HistoryEvent) -> str:
    if isinstance(entry, message.AssistantMessage):
        return _format_assistant(entry)
    if isinstance(entry, message.SideQuestionEntry):
        return entry.answer.strip()
    return ""


def _preview_lines(text: str, width: int) -> tuple[str, str]:
    single_line = " ".join(text.split())
    first_line, remaining = _split_at_cells(single_line, width)
    second_line, overflow = _split_at_cells(remaining, width)
    if overflow:
        second_line, _ = _split_at_cells(remaining, width - get_cwidth("…"))
        second_line = second_line.rstrip() + "…"
    return first_line, second_line


def _split_at_cells(text: str, width: int) -> tuple[str, str]:
    used = 0
    for index, char in enumerate(text):
        char_width = get_cwidth(char)
        if used + char_width > width:
            return text[:index].rstrip(), text[index:].lstrip()
        used += char_width
    return text, ""


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
