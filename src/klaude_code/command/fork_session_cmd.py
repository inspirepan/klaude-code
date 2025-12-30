import asyncio
import sys
from dataclasses import dataclass
from typing import Literal

from prompt_toolkit.styles import Style

from klaude_code.command.command_abc import Agent, CommandABC, CommandResult
from klaude_code.protocol import commands, events, model
from klaude_code.ui.terminal.selector import SelectItem, select_one

FORK_SELECT_STYLE = Style(
    [
        ("msg", ""),
        ("meta", "fg:ansibrightblack"),
        ("separator", "fg:ansibrightblack"),
        ("assistant", "fg:ansiblue"),
        ("pointer", "bold fg:ansigreen"),
        ("search_prefix", "fg:ansibrightblack"),
        ("search_success", "noinherit fg:ansigreen"),
        ("search_none", "noinherit fg:ansired"),
        ("question", "bold"),
        ("text", ""),
    ]
)


@dataclass
class ForkPoint:
    """A fork point in conversation history."""

    history_index: int | None  # None means fork entire conversation
    user_message: str
    tool_call_stats: dict[str, int]  # tool_name -> count
    last_assistant_summary: str


def _truncate(text: str, max_len: int = 60) -> str:
    """Truncate text to max_len, adding ellipsis if needed."""
    text = text.replace("\n", " ").strip()
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


def _build_fork_points(conversation_history: list[model.ConversationItem]) -> list[ForkPoint]:
    """Build list of fork points from conversation history.

    Fork points are:
    - Each UserMessageItem position (for UI display, including first which would be empty session)
    - The end of the conversation (fork entire conversation)
    """
    fork_points: list[ForkPoint] = []
    user_indices: list[int] = []

    for i, item in enumerate(conversation_history):
        if isinstance(item, model.UserMessageItem):
            user_indices.append(i)

    # For each UserMessageItem, create a fork point at that position
    for i, user_idx in enumerate(user_indices):
        user_item = conversation_history[user_idx]
        assert isinstance(user_item, model.UserMessageItem)

        # Find the end of this "task" (next UserMessageItem or end of history)
        next_user_idx = user_indices[i + 1] if i + 1 < len(user_indices) else len(conversation_history)

        # Count tool calls by name and find last assistant message in this segment
        tool_stats: dict[str, int] = {}
        last_assistant_content = ""
        for j in range(user_idx, next_user_idx):
            item = conversation_history[j]
            if isinstance(item, model.ToolCallItem):
                tool_stats[item.name] = tool_stats.get(item.name, 0) + 1
            elif isinstance(item, model.AssistantMessageItem) and item.content:
                last_assistant_content = item.content

        fork_points.append(
            ForkPoint(
                history_index=user_idx,
                user_message=user_item.content or "(empty)",
                tool_call_stats=tool_stats,
                last_assistant_summary=_truncate(last_assistant_content) if last_assistant_content else "",
            )
        )

    # Add the "fork entire conversation" option at the end
    if user_indices:
        fork_points.append(
            ForkPoint(
                history_index=None,  # None means fork entire conversation
                user_message="",  # No specific message, this represents the end
                tool_call_stats={},
                last_assistant_summary="",
            )
        )

    return fork_points


def _build_select_items(fork_points: list[ForkPoint]) -> list[SelectItem[int | None]]:
    """Build SelectItem list from fork points."""
    items: list[SelectItem[int | None]] = []

    for i, fp in enumerate(fork_points):
        is_first = i == 0
        is_last = i == len(fork_points) - 1

        # Build the title
        title_parts: list[tuple[str, str]] = []

        # First line: separator (with special markers for first/last fork points)
        if is_first and not is_last:
            title_parts.append(("class:separator", "----- fork from here (empty session) -----\n\n"))
        elif is_last:
            title_parts.append(("class:separator", "----- fork from here (entire session) -----\n\n"))
        else:
            title_parts.append(("class:separator", "----- fork from here -----\n\n"))

        if not is_last:
            # Second line: user message
            title_parts.append(("class:msg", f"user:   {_truncate(fp.user_message, 70)}\n"))

            # Third line: tool call stats (if any)
            if fp.tool_call_stats:
                tool_parts = [f"{name} × {count}" for name, count in fp.tool_call_stats.items()]
                title_parts.append(("class:meta", f"tools:  {', '.join(tool_parts)}\n"))

            # Fourth line: last assistant message summary (if any)
            if fp.last_assistant_summary:
                title_parts.append(("class:assistant", f"ai:     {fp.last_assistant_summary}\n"))

        # Empty line at the end
        title_parts.append(("class:text", "\n"))

        items.append(
            SelectItem(
                title=title_parts,
                value=fp.history_index,
                search_text=fp.user_message if not is_last else "fork entire conversation",
            )
        )

    return items


def _select_fork_point_sync(fork_points: list[ForkPoint]) -> int | None | Literal["cancelled"]:
    """Interactive fork point selection (sync version for asyncio.to_thread).

    Returns:
        - int: history index to fork at (exclusive)
        - None: fork entire conversation
        - "cancelled": user cancelled selection
    """
    items = _build_select_items(fork_points)
    if not items:
        return None

    # Default to the last option (fork entire conversation)
    last_value = items[-1].value

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
        return "Fork the current session and show a resume-by-id command"

    @property
    def is_interactive(self) -> bool:
        return True

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

        # Build fork points from conversation history
        fork_points = _build_fork_points(agent.session.conversation_history)

        if not fork_points:
            # Only one user message, just fork entirely
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

        # Interactive selection
        selected = await asyncio.to_thread(_select_fork_point_sync, fork_points)

        if selected == "cancelled":
            event = events.DeveloperMessageEvent(
                session_id=agent.session.id,
                item=model.DeveloperMessageItem(
                    content="(fork cancelled)",
                    command_output=model.CommandOutput(command_name=self.name),
                ),
            )
            return CommandResult(events=[event], persist_user_input=False, persist_events=False)

        # Perform the fork
        new_session = agent.session.fork(until_index=selected)
        await new_session.wait_for_flush()

        # Build result message
        fork_description = "entire conversation" if selected is None else f"up to message index {selected}"

        event = events.DeveloperMessageEvent(
            session_id=agent.session.id,
            item=model.DeveloperMessageItem(
                content=f"Session forked ({fork_description}). New session id: {new_session.id}",
                command_output=model.CommandOutput(
                    command_name=self.name,
                    ui_extra=model.SessionIdUIExtra(session_id=new_session.id),
                ),
            ),
        )
        return CommandResult(events=[event], persist_user_input=False, persist_events=False)
