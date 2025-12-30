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
    user_messages: list[str]
    messages_count: str
    relative_time: str
    model_name: str


def _format_message(msg: str) -> str:
    """Format a user message for display (strip and collapse newlines)."""
    return msg.strip().replace("\n", " ")


def format_user_messages_display(messages: list[str]) -> list[str]:
    """Format user messages for display in session selection.

    Shows up to 6 messages. If more than 6, shows first 3 and last 3 with ellipsis.
    Each message is on its own line.

    Args:
        messages: List of user messages.

    Returns:
        List of formatted message lines for display.
    """
    if len(messages) <= 6:
        return messages

    # More than 6: show first 3, ellipsis, last 3
    result = messages[:3]
    result.append("⋮")
    result.extend(messages[-3:])
    return result


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
        user_messages = [_format_message(m) for m in s.user_messages if m.strip()]
        if not user_messages:
            user_messages = ["N/A"]

        msg_count = "N/A" if s.messages_count == -1 else f"{s.messages_count} messages"
        model = s.model_name or "N/A"

        options.append(
            SessionSelectOption(
                session_id=str(s.id),
                user_messages=user_messages,
                messages_count=msg_count,
                relative_time=_relative_time(s.updated_at),
                model_name=model,
            )
        )

    return options
