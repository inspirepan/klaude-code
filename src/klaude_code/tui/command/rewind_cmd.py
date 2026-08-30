import asyncio
import sys
from typing import Literal

from klaude_code.protocol import events, message, op
from klaude_code.tui.terminal.selector import SelectItem, select_one

from .command_abc import Agent, CommandABC, CommandResult
from .fork_session_cmd import (
    ForkPoint,
    _build_fork_points,
    _fork_select_style,
    _style_fork_item,
    _truncate,
)
from .types import CommandName


def _build_rewind_select_items(fork_points: list[ForkPoint]) -> list[SelectItem[int]]:
    """Build SelectItem list for rewind points.

    Differs from the /fork picker in three ways: the separator wording says
    the discarded tail will be summarized (not silently dropped), "rewind
    entire conversation" sits at the TOP — it corresponds to the very start of
    the conversation, and with the dim transform pointing at it greys out the
    whole list (everything gets summarized) — and the topmost user point is
    not selectable (that case is already covered by the top entry, matching
    /fork's convention). Compaction-boundary points are excluded: there is no
    user message at that index to anchor the summary's pivot quote on.
    """

    items: list[SelectItem[int]] = []
    end_points = [fp for fp in fork_points if fp.kind == "end"]
    # Chronological order: user points as they appear in history.
    ordered_points = [fp for fp in fork_points if fp.kind != "end"]

    for fp in end_points:
        items.append(
            SelectItem(
                title=[
                    ("class:separator", "----- rewind entire conversation (summarize everything) -----\n\n"),
                    ("class:text", "\n"),
                ],
                value=fp.history_index,
                search_text="rewind entire conversation",
                selectable=True,
            )
        )

    first_user = True
    for fp in ordered_points:
        title_parts: list[tuple[str, str]] = []

        # The topmost user boundary needs no divider: nothing above it can be
        # summarized. It is also not selectable — "rewind entire conversation"
        # on top already covers summarizing everything.
        is_first_user = first_user
        first_user = False
        if not is_first_user:
            title_parts.append(("class:separator", "----- fork from here with summary below -----\n\n"))

        title_parts.append(("class:msg", f"user:   {_truncate(fp.user_message)}\n"))
        if fp.tool_call_stats:
            tool_parts = [f"{name} × {count}" for name, count in fp.tool_call_stats.items()]
            title_parts.append(("class:meta", f"tools:  {', '.join(tool_parts)}\n"))
        if fp.last_assistant_summary:
            title_parts.append(("class:assistant", f"ai:     {fp.last_assistant_summary}\n"))

        title_parts.append(("class:text", "\n"))
        items.append(
            SelectItem(
                title=title_parts,
                value=fp.history_index,
                search_text=fp.user_message,
                selectable=not is_first_user,
            )
        )
    return items


def _select_rewind_point_sync(fork_points: list[ForkPoint]) -> int | Literal["cancelled"]:
    """Interactive rewind point selection (sync version for asyncio.to_thread).

    Returns:
        - int: pivot index into conversation_history (exclusive), -1 = entire conversation
        - "cancelled": user cancelled selection
    """

    items = _build_rewind_select_items(fork_points)
    if not items:
        return -1

    last_value = items[-1].value
    if last_value is None:
        return -1

    if not sys.stdin.isatty() or not sys.stdout.isatty():
        return last_value

    try:
        result = select_one(
            message=(
                "Select rewind point (messages from this point to the end will be summarized into the new session):"
            ),
            items=items,
            pointer="→",
            style=_fork_select_style(),
            initial_value=last_value,
            highlight_pointed_item=True,
            # Same visual grammar as /fork: the pointed boundary's separator
            # turns green; rows at/after it dim (summarized, not kept).
            item_style_transform=_style_fork_item,
        )
        if result is None:
            return "cancelled"
        return result
    except KeyboardInterrupt:
        return "cancelled"


class RewindCommand(CommandABC):
    """Rewind the conversation to an earlier point.

    Forks a new session and carries the discarded tail over as a summary —
    nothing is lost, and the original session stays switchable. See
    ``agent/rewind/AGENTS.md``.
    """

    @property
    def name(self) -> CommandName:
        return CommandName.REWIND

    @property
    def summary(self) -> str:
        return "Rewind to an earlier point (the discarded tail is summarized into a new session)"

    @property
    def needs_history(self) -> bool:
        return True

    @property
    def is_interactive(self) -> bool:
        return True

    async def run(self, agent: Agent, user_input: message.UserInputPayload) -> CommandResult:
        del user_input  # unused

        if agent.session.messages_count == 0:
            event = events.NoticeEvent(
                session_id=agent.session.id,
                content="(no messages to rewind)",
                is_error=True,
            )
            return CommandResult(events=[event])

        fork_points = _build_fork_points(agent.session.conversation_history)
        if not fork_points:
            event = events.NoticeEvent(
                session_id=agent.session.id,
                content="(no messages to rewind)",
                is_error=True,
            )
            return CommandResult(events=[event])

        result = await asyncio.to_thread(_select_rewind_point_sync, fork_points)
        if result == "cancelled":
            event = events.NoticeEvent(
                session_id=agent.session.id,
                content="(rewind cancelled)",
            )
            return CommandResult(events=[event])

        # Anchor the pivot by exact text: the picker indexes the client's
        # rebuilt history view, which the server re-derives and validates
        # against (indices alone are ambiguous for compacted sessions).
        selected = next((fp for fp in fork_points if fp.history_index == result), None)
        pivot_text = None
        if selected is not None and selected.kind == "user":
            pivot_text = selected.user_message

        return CommandResult(
            events=[
                events.NoticeEvent(
                    session_id=agent.session.id,
                    content="Rewinding — summarizing the discarded tail…",
                )
            ],
            operations=[
                op.RewindWithSummaryOperation(
                    session_id=agent.session.id,
                    pivot_index=result,
                    pivot_text=pivot_text,
                )
            ],
        )
