import time

from klaude_code.trace import log, log_debug
from klaude_code.ui.terminal.selector import SelectItem, select_one

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
        from prompt_toolkit.styles import Style

        items: list[SelectItem[str]] = []
        for s in sessions:
            first_msg = s.first_user_message or "N/A"
            first_msg = first_msg.strip().replace("\n", " ")

            msg_count = "N/A" if s.messages_count == -1 else f"{s.messages_count} messages"
            model = s.model_name or "N/A"

            title = [
                ("class:msg", f"{first_msg}\n"),
                ("class:meta", f"   {msg_count} · {_relative_time(s.updated_at)} · {model} · {s.id}\n\n"),
            ]
            items.append(
                SelectItem(
                    title=title,
                    value=str(s.id),
                    search_text=f"{first_msg} {model} {s.id}",
                )
            )

        return select_one(
            message="Select a session to resume:",
            items=items,
            pointer="→",
            style=Style(
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
            ),
        )
    except Exception as e:
        log_debug(f"Failed to use prompt_toolkit for session select, {e}")

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
