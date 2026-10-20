# pyright: reportPrivateUsage=false

from __future__ import annotations

import asyncio
from typing import TextIO, cast
from unittest.mock import Mock

import pytest

from klaude_code.protocol import events
from klaude_code.tui import renderer as renderer_module
from klaude_code.tui.commands import RenderNotice, RenderTaskFinish
from klaude_code.tui.input.flicker_safe_stdout import FlickerSafeStdoutProxy
from klaude_code.tui.renderer import TASK_NOTIFICATION_DELAY_S, TUICommandRenderer
from klaude_code.tui.terminal.notifier import TerminalNotifier


def _finished() -> RenderTaskFinish:
    return RenderTaskFinish(event=events.TaskFinishEvent(session_id="main", task_result="done"))


def test_notification_wait_starts_after_frame_commit_and_does_not_block_next_event(monkeypatch) -> None:
    notifier = Mock(spec=TerminalNotifier)
    order: list[str] = []
    wait_started = asyncio.Event()
    release_notification = asyncio.Event()
    renderer = TUICommandRenderer(notifier=notifier)
    proxy = FlickerSafeStdoutProxy(raw=True)
    renderer.console.file = cast(TextIO, proxy)

    async def commit(text: str, *, before_write=None) -> None:
        order.append("commit")
        assert before_write is not None
        before_write()
        assert not notifier.notify.called
        order.append("frame-visible")

    async def wait_for_title(delay: float) -> None:
        assert delay == TASK_NOTIFICATION_DELAY_S
        order.append("notification-wait")
        wait_started.set()
        await release_notification.wait()

    notifier.notify.side_effect = lambda _notification: order.append("notify")
    monkeypatch.setattr(renderer_module, "write_scrollback_bulk", commit)
    monkeypatch.setattr(renderer_module.asyncio, "sleep", wait_for_title)

    async def run() -> None:
        await renderer.execute([_finished()])
        assert order == ["commit", "frame-visible"]
        await asyncio.wait_for(wait_started.wait(), timeout=1)
        await renderer.execute([RenderNotice(events.NoticeEvent(session_id="main", content="next event"))])
        assert order == ["commit", "frame-visible", "notification-wait", "commit", "frame-visible"]
        release_notification.set()
        await asyncio.gather(*renderer._notification_tasks)

    try:
        asyncio.run(run())
    finally:
        proxy.close()
    assert order[-1] == "notify"
    notifier.notify.assert_called_once()


def test_stop_cancels_pending_notification(monkeypatch) -> None:
    notifier = Mock(spec=TerminalNotifier)
    renderer = TUICommandRenderer(notifier=notifier)
    wait_started = asyncio.Event()
    monkeypatch.setattr(renderer_module.tty_state, "scrollback_write_in_flight", lambda: True)

    async def wait_for_title(delay: float) -> None:
        if delay == TASK_NOTIFICATION_DELAY_S:
            return
        assert delay == renderer_module.TASK_NOTIFICATION_TTY_POLL_S
        wait_started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(renderer_module.asyncio, "sleep", wait_for_title)

    async def run() -> None:
        await renderer.execute([_finished()])
        await asyncio.wait_for(wait_started.wait(), timeout=1)
        await renderer.stop()
        assert not renderer._notification_tasks

    asyncio.run(run())
    notifier.notify.assert_not_called()


@pytest.mark.parametrize("busy_reason", ["scrollback", "renderer_tail", "backpressure"])
def test_notification_waits_for_terminal_to_be_safe(monkeypatch, busy_reason: str) -> None:
    notifier = Mock(spec=TerminalNotifier)
    renderer = TUICommandRenderer(notifier=notifier)
    busy = True
    polling = asyncio.Event()
    continue_poll = asyncio.Event()

    monkeypatch.setattr(
        renderer_module.tty_state, "stdout_writable", lambda: not busy if busy_reason == "backpressure" else True
    )
    if busy_reason == "backpressure":
        monkeypatch.setattr(renderer_module.tty_state, "scrollback_write_in_flight", lambda: False)
    elif busy_reason == "scrollback":
        renderer_module.tty_state.push_scrollback_cycle()
    else:
        renderer_module.tty_state.set_renderer_tail_pending(True)

    async def wait(delay: float) -> None:
        if delay == TASK_NOTIFICATION_DELAY_S:
            return
        assert delay == renderer_module.TASK_NOTIFICATION_TTY_POLL_S
        polling.set()
        await continue_poll.wait()

    monkeypatch.setattr(renderer_module.asyncio, "sleep", wait)

    async def run() -> None:
        nonlocal busy
        await renderer.execute([_finished()])
        await asyncio.wait_for(polling.wait(), timeout=1)
        notifier.notify.assert_not_called()
        busy = False
        if busy_reason == "scrollback":
            renderer_module.tty_state.pop_scrollback_cycle()
        elif busy_reason == "renderer_tail":
            renderer_module.tty_state.set_renderer_tail_pending(False)
        continue_poll.set()
        await asyncio.gather(*renderer._notification_tasks)

    try:
        asyncio.run(run())
    finally:
        if busy_reason == "scrollback":
            renderer_module.tty_state.pop_scrollback_cycle()
        elif busy_reason == "renderer_tail":
            renderer_module.tty_state.set_renderer_tail_pending(False)
    notifier.notify.assert_called_once()


def test_replay_does_not_schedule_notification() -> None:
    notifier = Mock(spec=TerminalNotifier)
    renderer = TUICommandRenderer(notifier=notifier)

    async def run() -> None:
        renderer.set_replay_mode(True)
        await renderer.execute([_finished()])
        renderer.set_replay_mode(False)
        assert not renderer._notification_tasks

    asyncio.run(run())
    notifier.notify.assert_not_called()
