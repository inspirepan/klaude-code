import time
from typing import TYPE_CHECKING

from klaude_code.trace import log, log_debug

if TYPE_CHECKING:
    from questionary import Choice

from .session import Session


def _relative_time(ts: float) -> str:
    """Format timestamp as relative time like '5 days ago'."""
    now = time.time()
    diff = now - ts

    if diff < 60:
        return "just now"
    elif diff < 3600:
        mins = int(diff / 60)
        return f"{mins} minute{'s' if mins != 1 else ''} ago"
    elif diff < 86400:
        hours = int(diff / 3600)
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    elif diff < 604800:
        days = int(diff / 86400)
        return f"{days} day{'s' if days != 1 else ''} ago"
    elif diff < 2592000:
        weeks = int(diff / 604800)
        return f"{weeks} week{'s' if weeks != 1 else ''} ago"
    else:
        months = int(diff / 2592000)
        return f"{months} month{'s' if months != 1 else ''} ago"


def resume_select_session() -> str | None:
    sessions = Session.list_sessions()
    if not sessions:
        log("No sessions found for this project.")
        return None

    try:
        import questionary

        choices: list[Choice] = []
        for s in sessions:
            first_msg = s.first_user_message or "N/A"
            first_msg = first_msg.strip().replace("\n", " ")

            msg_count = "N/A" if s.messages_count == -1 else f"{s.messages_count} messages"
            model = s.model_name or "N/A"

            title = [
                ("class:msg", f"{first_msg}\n"),
                ("class:meta", f"   {_relative_time(s.updated_at)} · {msg_count} · {model}\n"),
            ]
            choices.append(questionary.Choice(title=title, value=s.id))

        return questionary.select(
            message="Select a session to resume:",
            choices=choices,
            pointer="→",
            instruction="↑↓ to move · type to search",
            use_jk_keys=False,
            use_search_filter=True,
            style=questionary.Style(
                [
                    ("msg", ""),
                    ("meta", "fg:ansibrightblack"),
                    ("pointer", "bold fg:ansicyan"),
                    ("highlighted", "fg:ansicyan"),
                    ("instruction", "fg:ansibrightblack"),
                    ("search_success", "noinherit fg:ansigreen"),
                    ("search_none", "noinherit fg:ansired"),
                ]
            ),
        ).ask()
    except Exception as e:
        log_debug(f"Failed to use questionary for session select, {e}")

        for i, s in enumerate(sessions, 1):
            first_msg = (s.first_user_message or "N/A").strip().replace("\n", " ")
            if len(first_msg) > 60:
                first_msg = first_msg[:59] + "…"
            msg_count = "N/A" if s.messages_count == -1 else f"{s.messages_count} msgs"
            model = s.model_name or "N/A"
            print(f"{i}. {first_msg}")
            print(f"   {_relative_time(s.updated_at)} · {msg_count} · {model}")
        try:
            raw = input("Select a session number: ").strip()
            idx = int(raw)
            if 1 <= idx <= len(sessions):
                return str(sessions[idx - 1].id)
        except (ValueError, EOFError):
            return None
    return None
