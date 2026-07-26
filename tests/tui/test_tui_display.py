# pyright: reportPrivateUsage=false

from __future__ import annotations

import asyncio
import io
from unittest.mock import Mock

import pytest
from rich.console import Console

from klaude_code.protocol import events, tools
from klaude_code.tui import renderer as renderer_module
from klaude_code.tui.commands import RenderTaskFinish, RenderToolCall, StopTitleBlink, UpdateTerminalTitlePrefix
from klaude_code.tui.display import TUIDisplay
from klaude_code.tui.terminal.notifier import Notification, NotificationType, TerminalNotifier
from klaude_code.tui.transcript_detail import Detail


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
    display._renderer.set_transcript_detail(Detail.FULL)

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

    assert display._renderer._continuous_block_session_id is None
    assert output.getvalue().endswith("\n\n")


def test_cancelled_task_skips_notification(monkeypatch: pytest.MonkeyPatch) -> None:
    notifier = Mock(spec=TerminalNotifier)
    display = TUIDisplay(notifier=notifier)
    monkeypatch.setattr(renderer_module.asyncio, "sleep", Mock(side_effect=AssertionError("unexpected delay")))

    asyncio.run(
        display._renderer.execute(
            [
                RenderTaskFinish(
                    event=events.TaskFinishEvent(
                        session_id="main",
                        task_result="task cancelled",
                    )
                )
            ]
        )
    )

    notifier.notify.assert_not_called()


def test_task_notification_follows_final_terminal_title(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    notifier = Mock(spec=TerminalNotifier)
    notifier.notify.side_effect = lambda _notification: calls.append("notify")
    display = TUIDisplay(notifier=notifier)

    monkeypatch.setattr(renderer_module, "is_title_blinking", lambda: False)
    monkeypatch.setattr(renderer_module, "stop_terminal_title_blink", lambda: calls.append("stop"))

    async def _sleep(delay: float) -> None:
        assert delay == pytest.approx(0.3)
        calls.append("wait")

    monkeypatch.setattr(renderer_module.asyncio, "sleep", _sleep)
    monkeypatch.setattr(
        renderer_module,
        "update_terminal_title",
        lambda *_args, **kwargs: calls.append(f"title:{kwargs['prefix']}"),
    )

    asyncio.run(
        display._renderer.execute(
            [
                RenderTaskFinish(event=events.TaskFinishEvent(session_id="main", task_result="done")),
                StopTitleBlink(),
                UpdateTerminalTitlePrefix(prefix="✅", model_name="gpt-5", session_title="Task"),
            ]
        )
    )

    assert calls == ["stop", "title:✅", "wait", "notify"]


def test_interrupt_cancelled_task_suggests_continue() -> None:
    suggestions: list[str | None] = []
    display = TUIDisplay(notifier=Mock(spec=TerminalNotifier), on_prompt_suggestion=suggestions.append)

    display._handle_prompt_suggestion_event(events.InterruptEvent(session_id="main"))
    display._handle_prompt_suggestion_event(events.TaskFinishEvent(session_id="main", task_result="task cancelled"))

    assert suggestions == ["/continue"]


def test_interrupt_without_visible_output_does_not_suggest_continue() -> None:
    suggestions: list[str | None] = []
    display = TUIDisplay(notifier=Mock(spec=TerminalNotifier), on_prompt_suggestion=suggestions.append)

    display._handle_prompt_suggestion_event(events.InterruptEvent(session_id="main", show_notice=False))
    display._handle_prompt_suggestion_event(events.TaskFinishEvent(session_id="main", task_result="task cancelled"))

    assert suggestions == []


def test_replay_interrupt_cancelled_task_restores_continue_suggestion() -> None:
    suggestions: list[str | None] = []
    display = TUIDisplay(notifier=Mock(spec=TerminalNotifier), on_prompt_suggestion=suggestions.append)

    display._restore_prompt_suggestion_from_replay(
        [
            events.InterruptEvent(session_id="main"),
            events.TaskFinishEvent(session_id="main", task_result="task cancelled"),
        ]
    )

    assert suggestions == ["/continue"]


def test_replay_interrupt_without_visible_output_does_not_restore_continue_suggestion() -> None:
    suggestions: list[str | None] = []
    display = TUIDisplay(notifier=Mock(spec=TerminalNotifier), on_prompt_suggestion=suggestions.append)

    display._restore_prompt_suggestion_from_replay(
        [
            events.InterruptEvent(session_id="main", show_notice=False),
            events.TaskFinishEvent(session_id="main", task_result="task cancelled"),
        ]
    )

    assert suggestions == []
