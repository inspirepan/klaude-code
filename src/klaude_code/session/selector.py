from dataclasses import dataclass

from .session import Session


def _format_time(ts: float) -> str:
    """Format timestamp as absolute time like '01-01 14:30'."""
    from datetime import datetime

    dt = datetime.fromtimestamp(ts)
    return dt.strftime("%m-%d %H:%M")


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
                relative_time=_format_time(s.updated_at),
                model_name=model,
            )
        )

    return options
