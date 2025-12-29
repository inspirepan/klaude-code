import time
from dataclasses import dataclass

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


@dataclass(frozen=True, slots=True)
class SessionSelectOption:
    """Option data for session selection UI."""

    session_id: str
    first_user_message: str
    messages_count: str
    relative_time: str
    model_name: str


def build_session_select_options() -> list[SessionSelectOption]:
    """Build session selection options data.

    Returns:
        List of SessionSelectOption, or empty list if no sessions exist.
    """
    sessions = Session.list_sessions()
    if not sessions:
        return []

    options: list[SessionSelectOption] = []
    for s in sessions:
        first_msg = s.first_user_message or "N/A"
        first_msg = first_msg.strip().replace("\n", " ")

        msg_count = "N/A" if s.messages_count == -1 else f"{s.messages_count} messages"
        model = s.model_name or "N/A"

        options.append(
            SessionSelectOption(
                session_id=str(s.id),
                first_user_message=first_msg,
                messages_count=msg_count,
                relative_time=_relative_time(s.updated_at),
                model_name=model,
            )
        )

    return options
