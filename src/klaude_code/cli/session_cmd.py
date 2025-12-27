import time

import typer

from klaude_code.session import Session
from klaude_code.trace import log


def _session_confirm(sessions: list[Session.SessionMetaBrief], message: str) -> bool:
    """Show session list and confirm deletion using prompt_toolkit."""

    from prompt_toolkit.styles import Style

    from klaude_code.ui.terminal.selector import SelectItem, select_one

    def _fmt(ts: float) -> str:
        try:
            return time.strftime("%m-%d %H:%M:%S", time.localtime(ts))
        except (OSError, OverflowError, ValueError):
            return str(ts)

    log(f"Sessions to delete ({len(sessions)}):")
    for s in sessions:
        msg_count_display = "N/A" if s.messages_count == -1 else str(s.messages_count)
        first_msg = (s.first_user_message or "").strip().replace("\n", " ")[:50]
        if len(s.first_user_message or "") > 50:
            first_msg += "..."
        log(f"  {_fmt(s.updated_at)}  {msg_count_display:>3} msgs  {first_msg}")

    items: list[SelectItem[bool]] = [
        SelectItem(title=[("class:text", "No\n")], value=False, search_text="No"),
        SelectItem(title=[("class:text", "Yes\n")], value=True, search_text="Yes"),
    ]

    result = select_one(
        message=message,
        items=items,
        pointer="→",
        style=Style(
            [
                ("question", "bold"),
                ("pointer", "ansigreen"),
                ("highlighted", "ansigreen"),
                ("text", ""),
            ]
        ),
        use_search_filter=False,
    )
    return bool(result)


def session_clean(
    min_messages: int = typer.Option(5, "--min", "-n", help="Minimum messages to keep a session"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
) -> None:
    """Remove sessions with fewer than N messages (default: 5)"""
    sessions = Session.list_sessions()
    to_delete = [s for s in sessions if 0 <= s.messages_count < min_messages]

    if not to_delete:
        log(f"No sessions with fewer than {min_messages} messages found.")
        return

    if not yes and not _session_confirm(to_delete, "Delete these sessions?"):
        log("Aborted.")
        return

    deleted = Session.clean_small_sessions(min_messages)
    log(f"Deleted {deleted} session(s).")


def session_clean_all(
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
) -> None:
    """Remove all sessions for the current project"""
    sessions = Session.list_sessions()

    if not sessions:
        log("No sessions found.")
        return

    if not yes and not _session_confirm(sessions, "Delete ALL sessions? This cannot be undone."):
        log("Aborted.")
        return

    deleted = Session.clean_all_sessions()
    log(f"Deleted {deleted} session(s).")


def register_session_commands(app: typer.Typer) -> None:
    """Register session subcommands to the given Typer app."""
    session_app = typer.Typer(help="Manage sessions for the current project")
    session_app.command("clean")(session_clean)
    session_app.command("clean-all")(session_clean_all)
    app.add_typer(session_app, name="session")
