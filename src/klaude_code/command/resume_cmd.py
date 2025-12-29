import asyncio

from prompt_toolkit.styles import Style

from klaude_code.command.command_abc import Agent, CommandABC, CommandResult
from klaude_code.protocol import commands, events, model, op
from klaude_code.session.selector import build_session_select_options
from klaude_code.trace import log
from klaude_code.ui.terminal.selector import SelectItem, select_one

SESSION_SELECT_STYLE = Style(
    [
        ("msg", ""),
        ("meta", "fg:ansibrightblack"),
        ("pointer", "bold fg:ansigreen"),
        ("highlighted", "fg:ansigreen"),
        ("search_prefix", "fg:ansibrightblack"),
        ("search_success", "noinherit fg:ansigreen"),
        ("search_none", "noinherit fg:ansired"),
        ("question", "bold"),
        ("text", ""),
    ]
)


def _select_session_sync() -> str | None:
    """Interactive session selection (sync version for asyncio.to_thread)."""
    options = build_session_select_options()
    if not options:
        log("No sessions found for this project.")
        return None

    items: list[SelectItem[str]] = []
    for opt in options:
        title = [
            ("class:msg", f"{opt.first_user_message}\n"),
            ("class:meta", f"   {opt.messages_count} · {opt.relative_time} · {opt.model_name} · {opt.session_id}\n\n"),
        ]
        items.append(
            SelectItem(
                title=title,
                value=opt.session_id,
                search_text=f"{opt.first_user_message} {opt.model_name} {opt.session_id}",
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

        selected_session_id = await asyncio.to_thread(_select_session_sync)
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
