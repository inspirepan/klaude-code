import time
from typing import TYPE_CHECKING

from klaude_code.trace import log, log_debug

if TYPE_CHECKING:
    from questionary import Choice

from .session import Session


def resume_select_session() -> str | None:
    # Column widths
    UPDATED_AT_WIDTH = 16
    MSG_COUNT_WIDTH = 3
    MODEL_WIDTH = 25
    FIRST_MESSAGE_WIDTH = 50
    sessions = Session.list_sessions()
    if not sessions:
        log("No sessions found for this project.")
        return None

    def _fmt(ts: float) -> str:
        try:
            return time.strftime("%m-%d %H:%M:%S", time.localtime(ts))
        except Exception:
            return str(ts)

    try:
        import questionary

        choices: list[Choice] = []
        for s in sessions:
            first_user_message = s.first_user_message or "N/A"
            msg_count_display = "N/A" if s.messages_count == -1 else str(s.messages_count)
            model_display = s.model_name or "N/A"

            title = [
                ("class:d", f"{_fmt(s.updated_at):<{UPDATED_AT_WIDTH}} "),
                ("class:b", f"{msg_count_display:>{MSG_COUNT_WIDTH}}  "),
                (
                    "class:t",
                    f"{model_display[: MODEL_WIDTH - 1] + '…' if len(model_display) > MODEL_WIDTH else model_display:<{MODEL_WIDTH}}  ",
                ),
                (
                    "class:t",
                    f"{first_user_message.strip().replace('\n', ' ↩ '):<{FIRST_MESSAGE_WIDTH}}",
                ),
            ]
            choices.append(questionary.Choice(title=title, value=s.id))
        return questionary.select(
            message=f"{' Updated at':<{UPDATED_AT_WIDTH + 1}} {'Msg':>{MSG_COUNT_WIDTH}}  {'Model':<{MODEL_WIDTH}}  {'First message':<{FIRST_MESSAGE_WIDTH}}",
            choices=choices,
            pointer="→",
            instruction="↑↓ to move",
            style=questionary.Style(
                [
                    ("t", ""),
                    ("b", "bold"),
                    ("d", "dim"),
                ]
            ),
        ).ask()
    except Exception as e:
        log_debug(f"Failed to use questionary for session select, {e}")

        for i, s in enumerate(sessions, 1):
            msg_count_display = "N/A" if s.messages_count == -1 else str(s.messages_count)
            model_display = s.model_name or "N/A"
            print(
                f"{i}. {_fmt(s.updated_at)}  {msg_count_display:>{MSG_COUNT_WIDTH}} "
                f"{model_display[: MODEL_WIDTH - 1] + '…' if len(model_display) > MODEL_WIDTH else model_display:<{MODEL_WIDTH}} {s.id}  {s.work_dir}"
            )
        try:
            raw = input("Select a session number: ").strip()
            idx = int(raw)
            if 1 <= idx <= len(sessions):
                return str(sessions[idx - 1].id)
        except Exception:
            return None
    return None
