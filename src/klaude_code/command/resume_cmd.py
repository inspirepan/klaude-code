import asyncio

from prompt_toolkit.styles import Style

from klaude_code.command.command_abc import Agent, CommandABC, CommandResult
from klaude_code.protocol import commands, events, model, op
from klaude_code.session.selector import build_session_select_options, format_user_messages_display
from klaude_code.trace import log
from klaude_code.ui.terminal.selector import SelectItem, select_one

SESSION_SELECT_STYLE = Style(
    [
        ("msg", "fg:ansibrightblack"),
        ("meta", ""),
        ("pointer", "bold fg:ansigreen"),
        ("highlighted", "fg:ansigreen"),
        ("search_prefix", "fg:ansibrightblack"),
        ("search_success", "noinherit fg:ansigreen"),
        ("search_none", "noinherit fg:ansired"),
        ("question", "bold"),
        ("text", ""),
    ]
)


def select_session_sync() -> str | None:
    """Interactive session selection (sync version for asyncio.to_thread)."""
    options = build_session_select_options()
    if not options:
        log("No sessions found for this project.")
        return None

    items: list[SelectItem[str]] = []
    for idx, opt in enumerate(options, 1):
        display_msgs = format_user_messages_display(opt.user_messages)
        title: list[tuple[str, str]] = []
        title.append(("fg:ansibrightblack", f"{idx:2}. "))
        title.append(
            ("class:meta", f"{opt.relative_time} · {opt.messages_count} · {opt.model_name} · {opt.session_id}\n")
        )
        for msg in display_msgs:
            if msg == "⋮":
                title.append(("class:msg", f"    {msg}\n"))
            else:
                title.append(("class:msg", f"    > {msg}\n"))
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
            style=SESSION_SELECT_STYLE,
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

        selected_session_id = await asyncio.to_thread(select_session_sync)
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
