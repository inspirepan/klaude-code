# pyright: reportPrivateUsage=false

from __future__ import annotations

import asyncio
import io
from unittest.mock import Mock

from rich.console import Console

from klaude_code.protocol import events, tools
from klaude_code.tui.commands import RenderToolCall
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

def test_hide_progress_ui_flushes_open_renderer_blocks() -> None:
    display = TUIDisplay(notifier=Mock(spec=TerminalNotifier))
    output = io.StringIO()
    display._renderer.console = Console(
        file=output,
        theme=display._renderer.themes.app_theme,
        width=100,
        force_terminal=False,
    )
    display._renderer.console.push_theme(display._renderer.themes.markdown_theme)

    asyncio.run(
        display._renderer.execute(
            [
                RenderToolCall(
                    event=events.ToolCallEvent(
                        session_id="main",
                        tool_call_id="tool-1",
                        tool_name=tools.BASH,
                        arguments='{"command":"echo hi"}',
                    )
                )
            ]
        )
    )

    display.hide_progress_ui()

    assert display._renderer._tool_block_open is False
    assert output.getvalue().endswith("\n\n")
