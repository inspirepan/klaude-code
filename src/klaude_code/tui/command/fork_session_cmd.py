import asyncio
import sys
from dataclasses import dataclass
from typing import Literal

from prompt_toolkit.styles import Style, merge_styles

from klaude_code.protocol import commands, events, message, model
from klaude_code.session import Session
from klaude_code.tui.input.key_bindings import copy_to_clipboard
from klaude_code.tui.terminal.selector import DEFAULT_PICKER_STYLE, SelectItem, select_one

from .command_abc import Agent, CommandABC, CommandResult

FORK_SELECT_STYLE = merge_styles(
    [
        DEFAULT_PICKER_STYLE,
        Style(
            [
                ("separator", "fg:ansibrightblack"),
                ("assistant", "fg:ansiblue"),
            ]
        ),
    ]
)


@dataclass
class ForkPoint:
    """A fork point in conversation history."""

    kind: Literal["user", "compaction", "end"]
    history_index: int  # -1 means fork entire conversation
    tool_call_stats: dict[str, int]  # tool_name -> count
    user_message: str = ""
    last_assistant_summary: str = ""
    compaction_summary_preview: str = ""
    compaction_first_kept_index: int | None = None
    compaction_tokens_before: int | None = None


def _truncate(text: str, max_len: int = 60) -> str:
    """Truncate text to max_len, adding ellipsis if needed."""
    text = text.replace("\n", " ").strip()
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"


def _first_non_empty_line(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def _preview_compaction_summary(summary: str) -> str:
    """Return a human-friendly preview line for a CompactionEntry summary.

    Compaction summaries may start with a fixed prefix line and may contain <summary> tags.
    For UI previews we want something more informative than the prefix.
    """

    cleaned = summary.replace("<summary>", "\n").replace("</summary>", "\n")
    lines = [line.strip() for line in cleaned.splitlines()]
    prefix = "the conversation history before this point was compacted"

    def _is_noise(line: str) -> bool:
        if not line:
            return True
        if line.casefold().startswith(prefix):
            return True
        return line in {"---", "----", "-----"}

    # Prefer the first non-empty line under the "## Goal" section.
    for i, line in enumerate(lines):
        if line == "## Goal":
            for j in range(i + 1, len(lines)):
                candidate = lines[j]
                if _is_noise(candidate):
                    continue
                if candidate.startswith("## "):
                    break
                return candidate

    # Otherwise, pick the first non-heading meaningful line.
    for line in lines:
        if _is_noise(line):
            continue
        if line.startswith("## "):
            continue
        return line

    # Fallback: first non-empty line.
    return _first_non_empty_line(cleaned)


def _build_fork_points(conversation_history: list[message.HistoryEvent]) -> list[ForkPoint]:
    """Build list of fork points from conversation history.

    Fork points are:
    - Each UserMessage position (for UI display, including first which would be empty session)
    - The latest CompactionEntry boundary (just after it)
    - The end of the conversation (fork entire conversation)
    """
    fork_points: list[ForkPoint] = []
    user_indices: list[int] = []

    for i, item in enumerate(conversation_history):
        if isinstance(item, message.UserMessage):
            user_indices.append(i)

    # For each UserMessage, create a fork point at that position
    for i, user_idx in enumerate(user_indices):
        user_item = conversation_history[user_idx]
        assert isinstance(user_item, message.UserMessage)

        # Find the end of this "task" (next UserMessage or end of history)
        next_user_idx = user_indices[i + 1] if i + 1 < len(user_indices) else len(conversation_history)

        # Count tool calls by name and find last assistant message in this segment
        tool_stats: dict[str, int] = {}
        last_assistant_content = ""
        for j in range(user_idx, next_user_idx):
            item = conversation_history[j]
            if isinstance(item, message.AssistantMessage):
                for part in item.parts:
                    if isinstance(part, message.ToolCallPart):
                        tool_stats[part.tool_name] = tool_stats.get(part.tool_name, 0) + 1
                text = message.join_text_parts(item.parts)
                if text:
                    last_assistant_content = text

        user_text = message.join_text_parts(user_item.parts)
        fork_points.append(
            ForkPoint(
                kind="user",
                history_index=user_idx,
                tool_call_stats=tool_stats,
                user_message=user_text or "(empty)",
                last_assistant_summary=_truncate(last_assistant_content) if last_assistant_content else "",
            )
        )

    # Add a fork point just after the latest compaction entry (if any).
    last_compaction_idx = -1
    last_compaction: message.CompactionEntry | None = None
    for idx in range(len(conversation_history) - 1, -1, -1):
        item = conversation_history[idx]
        if isinstance(item, message.CompactionEntry):
            last_compaction_idx = idx
            last_compaction = item
            break
    if last_compaction is not None:
        # `until_index` is exclusive; `idx + 1` means include the CompactionEntry itself.
        boundary_index = min(len(conversation_history), last_compaction_idx + 1)
        preview = _truncate(_preview_compaction_summary(last_compaction.summary), 70)
        fork_points.append(
            ForkPoint(
                kind="compaction",
                history_index=boundary_index,
                tool_call_stats={},
                compaction_summary_preview=preview,
                compaction_first_kept_index=last_compaction.first_kept_index,
                compaction_tokens_before=last_compaction.tokens_before,
            )
        )

    fork_points.sort(key=lambda fp: fp.history_index)

    # Add the "fork entire conversation" option at the end
    if fork_points:
        fork_points.append(ForkPoint(kind="end", history_index=-1, tool_call_stats={}))

    return fork_points


def _build_select_items(fork_points: list[ForkPoint]) -> list[SelectItem[int]]:
    """Build SelectItem list from fork points."""
    items: list[SelectItem[int]] = []

    for i, fp in enumerate(fork_points):
        is_first = i == 0

        # Build the title
        title_parts: list[tuple[str, str]] = []

        # First line: separator (with special markers for first/last fork points)
        if is_first:
            pass
        elif fp.kind == "end":
            title_parts.append(("class:separator", "----- fork from here (entire session) -----\n\n"))
        elif fp.kind == "compaction":
            title_parts.append(("class:separator", "----- fork after compaction -----\n\n"))
        else:
            title_parts.append(("class:separator", "----- fork from here -----\n\n"))

        if fp.kind == "user":
            # Second line: user message
            title_parts.append(("class:msg", f"user:   {_truncate(fp.user_message, 70)}\n"))

            # Third line: tool call stats (if any)
            if fp.tool_call_stats:
                tool_parts = [f"{name} × {count}" for name, count in fp.tool_call_stats.items()]
                title_parts.append(("class:meta", f"tools:  {', '.join(tool_parts)}\n"))

            # Fourth line: last assistant message summary (if any)
            if fp.last_assistant_summary:
                title_parts.append(("class:assistant", f"ai:     {fp.last_assistant_summary}\n"))

        elif fp.kind == "compaction":
            kept_from = fp.compaction_first_kept_index
            if kept_from is not None:
                title_parts.append(("class:meta", f"kept:   from history index {kept_from}\n"))
            if fp.compaction_tokens_before is not None:
                title_parts.append(("class:meta", f"tokens: {fp.compaction_tokens_before}\n"))
            if fp.compaction_summary_preview:
                title_parts.append(("class:assistant", f"sum:    {fp.compaction_summary_preview}\n"))

        # Empty line at the end
        title_parts.append(("class:text", "\n"))

        items.append(
            SelectItem(
                title=title_parts,
                value=fp.history_index,
                search_text=(
                    fp.user_message
                    if fp.kind == "user"
                    else (
                        f"compaction {fp.compaction_summary_preview}"
                        if fp.kind == "compaction"
                        else "fork entire conversation"
                    )
                ),
                selectable=not (fp.kind == "user" and is_first),
            )
        )

    return items


def _select_fork_point_sync(fork_points: list[ForkPoint]) -> int | Literal["cancelled"]:
    """Interactive fork point selection (sync version for asyncio.to_thread).

    Returns:
        - int: history index to fork at (exclusive), -1 means fork entire conversation
        - "cancelled": user cancelled selection
    """
    items = _build_select_items(fork_points)
    if not items:
        return -1

    # Default to the last option (fork entire conversation)
    last_value = items[-1].value
    if last_value is None:
        # Should not happen as we populate all items with int values
        return -1

    # Non-interactive environments default to forking entire conversation
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        return last_value

    try:
        result = select_one(
            message="Select fork point (messages before this point will be included):",
            items=items,
            pointer="→",
            style=FORK_SELECT_STYLE,
            initial_value=last_value,
            highlight_pointed_item=False,
        )
        if result is None:
            return "cancelled"
        return result
    except KeyboardInterrupt:
        return "cancelled"


class ForkSessionCommand(CommandABC):
    """Fork current session to a new session id and show a resume command."""

    @property
    def name(self) -> commands.CommandName:
        return commands.CommandName.FORK_SESSION

    @property
    def summary(self) -> str:
        return "Fork the current session and show a resume command"

    @property
    def is_interactive(self) -> bool:
        return True

    async def run(self, agent: Agent, user_input: message.UserInputPayload) -> CommandResult:
        del user_input  # unused

        if agent.session.messages_count == 0:
            event = events.CommandOutputEvent(
                session_id=agent.session.id,
                command_name=self.name,
                content="(no messages to fork)",
                is_error=True,
            )
            return CommandResult(events=[event])

        # Build fork points from conversation history
        fork_points = _build_fork_points(agent.session.conversation_history)

        if not fork_points:
            # Only one user message, just fork entirely
            new_session = agent.session.fork()
            await new_session.wait_for_flush()

            short_id = Session.shortest_unique_prefix(new_session.id)
            resume_cmd = f"klaude -r {short_id}"
            copy_to_clipboard(resume_cmd)

            event = events.CommandOutputEvent(
                session_id=agent.session.id,
                command_name=self.name,
                content=f"Session forked successfully. New session id: {new_session.id}",
                ui_extra=model.SessionIdUIExtra(session_id=new_session.id),
            )
            return CommandResult(events=[event])

        # Interactive selection
        selected = await asyncio.to_thread(_select_fork_point_sync, fork_points)

        if selected == "cancelled":
            event = events.CommandOutputEvent(
                session_id=agent.session.id,
                command_name=self.name,
                content="(fork cancelled)",
            )
            return CommandResult(events=[event])

        # Perform the fork
        new_session = agent.session.fork(until_index=selected)
        await new_session.wait_for_flush()

        # Build result message
        selected_point = next((fp for fp in fork_points if fp.history_index == selected), None)
        if selected_point is not None and selected_point.kind == "compaction":
            fork_description = "after compaction"
        else:
            fork_description = "entire conversation" if selected == -1 else f"up to message index {selected}"

        short_id = Session.shortest_unique_prefix(new_session.id)
        resume_cmd = f"klaude -r {short_id}"
        copy_to_clipboard(resume_cmd)

        event = events.CommandOutputEvent(
            session_id=agent.session.id,
            command_name=self.name,
            content=f"Session forked ({fork_description}). New session id: {new_session.id}",
            ui_extra=model.SessionIdUIExtra(session_id=new_session.id),
        )
        return CommandResult(events=[event])
