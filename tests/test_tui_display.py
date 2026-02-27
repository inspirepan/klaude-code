from __future__ import annotations

from unittest.mock import Mock

from klaude_code.tui.display import TUIDisplay
from klaude_code.tui.terminal.notifier import Notification, NotificationType, TerminalNotifier


def test_notify_ask_user_question_emits_terminal_notification() -> None:
    notifier = Mock(spec=TerminalNotifier)
    display = TUIDisplay(notifier=notifier)

    display.notify_ask_user_question(question_count=2)

    notifier.notify.assert_called_once()
    sent = notifier.notify.call_args.args[0]
    assert isinstance(sent, Notification)
    assert sent.type == NotificationType.ASK_USER_QUESTION
    assert sent.title == "Input Required"
    assert sent.body == "2 questions waiting for your answer"


def test_notify_ask_user_question_skips_empty_payload() -> None:
    notifier = Mock(spec=TerminalNotifier)
    display = TUIDisplay(notifier=notifier)

    display.notify_ask_user_question(question_count=0)

    notifier.notify.assert_not_called()
