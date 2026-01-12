import asyncio

from klaude_code.log import log
from klaude_code.protocol import commands, events, message, op
from klaude_code.session.selector import build_session_select_options, format_user_messages_display
from klaude_code.tui.terminal.selector import DEFAULT_PICKER_STYLE, SelectItem, select_one

from .command_abc import Agent, CommandABC, CommandResult


def select_session_sync(session_ids: list[str] | None = None) -> str | None:
    """Interactive session selection (sync version for asyncio.to_thread).

    Args:
        session_ids: Optional list of session IDs to filter. If provided, only show these sessions.
    """
    options = build_session_select_options()
    if session_ids is not None:
        session_id_set = set(session_ids)
        options = [opt for opt in options if opt.session_id in session_id_set]
    if not options:
        log("No sessions found for this project.")
        return None

    items: list[SelectItem[str]] = []
    for idx, opt in enumerate(options, 1):
        display_msgs = format_user_messages_display(opt.user_messages)
        title: list[tuple[str, str]] = []
        title.append(("fg:ansibrightblack", f"{idx:2}. "))
        title.append(("class:meta", f"{opt.relative_time} · {opt.messages_count} · {opt.model_name}"))
        title.append(("fg:ansibrightblack dim", f" · {opt.session_id}\n"))
        for i, msg in enumerate(display_msgs):
            is_last = i == len(display_msgs) - 1
            if msg == "⋮":
                title.append(("class:msg", f"    {msg}\n"))
            else:
                prefix = "╰─" if is_last else "├─"
                title.append(("fg:ansibrightblack dim", f"    {prefix} "))
                title.append(("class:msg", f"{msg}\n"))
        title.append(("", "\n"))

        search_text = " ".join(opt.user_messages) + f" {opt.model_name} {opt.session_id}"
        items.append(
            SelectItem(
                title=title,
                value=opt.session_id,
                search_text=search_text,
            )
        )

    try:
        return select_one(
            message="Select a session to resume:",
            items=items,
            pointer="→",
            style=DEFAULT_PICKER_STYLE,
        )
    except KeyboardInterrupt:
        return None


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

    async def run(self, agent: Agent, user_input: message.UserInputPayload) -> CommandResult:
        del user_input  # unused

        if agent.session.messages_count > 0:
            event = events.CommandOutputEvent(
                session_id=agent.session.id,
                command_name=self.name,
                content="Cannot resume: current session already has messages. Use `klaude -r` to start a new instance with session selection.",
                is_error=True,
            )
            return CommandResult(events=[event])

        selected_session_id = await asyncio.to_thread(select_session_sync)
        if selected_session_id is None:
            event = events.CommandOutputEvent(
                session_id=agent.session.id,
                command_name=self.name,
                content="(no session selected)",
            )
            return CommandResult(events=[event])

        return CommandResult(
            operations=[op.ResumeSessionOperation(target_session_id=selected_session_id)],
        )
