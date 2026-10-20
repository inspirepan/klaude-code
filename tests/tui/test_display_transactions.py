"""Display transitions and their terminal frames must retain one order."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable
from typing import Any

from rich.text import Text

from klaude_code.protocol import events
from klaude_code.tui import display as display_module
from klaude_code.tui.display import TUIDisplay

from .test_transcript_toggle import make_envelope


def test_toast_waits_for_inflight_event_and_clear_waits_for_toast(monkeypatch: Any) -> None:
    async def scenario() -> None:
        display = TUIDisplay()
        started = asyncio.Event()
        release = asyncio.Event()
        cleared = asyncio.Event()
        order: list[str] = []

        def transition(_event: events.Event) -> list[str]:
            order.append("event-transition")
            return ["event"]

        def show() -> list[str]:
            order.append("show-transition")
            return ["show"]

        def clear() -> list[str]:
            order.append("clear-transition")
            return ["clear"]

        async def execute(commands: list[str]) -> None:
            if commands == ["event"]:
                started.set()
                await release.wait()
            order.append(f"{commands[0]}-commit")
            if commands == ["clear"]:
                cleared.set()

        monkeypatch.setattr(display._machine, "transition", transition)
        monkeypatch.setattr(display._machine, "show_sigint_exit_toast", show)
        monkeypatch.setattr(display._machine, "clear_sigint_exit_toast", clear)
        monkeypatch.setattr(display._renderer, "execute", execute)

        consuming = asyncio.create_task(
            display.consume_envelope(make_envelope(events.NoticeEvent(session_id="main", content="first")))
        )
        await started.wait()
        display.show_sigint_exit_toast(window_seconds=0)
        await asyncio.sleep(0)
        assert order == ["event-transition"]
        release.set()
        await consuming
        await asyncio.wait_for(cleared.wait(), timeout=1)
        assert order == [
            "event-transition",
            "event-commit",
            "show-transition",
            "show-commit",
            "clear-transition",
            "clear-commit",
        ]
        await display.stop()

    asyncio.run(scenario())


def test_cancelled_event_releases_display_lock_for_toast(monkeypatch: Any) -> None:
    async def scenario() -> None:
        display = TUIDisplay()
        started = asyncio.Event()
        toast_committed = asyncio.Event()

        async def execute(commands: list[Any]) -> None:
            if commands == ["event"]:
                started.set()
                await asyncio.Event().wait()
            elif commands == ["show"]:
                toast_committed.set()

        monkeypatch.setattr(display._machine, "transition", lambda _event: ["event"])
        monkeypatch.setattr(display._machine, "show_sigint_exit_toast", lambda: ["show"])
        monkeypatch.setattr(display._renderer, "execute", execute)
        consuming = asyncio.create_task(
            display.consume_envelope(make_envelope(events.NoticeEvent(session_id="main", content="first")))
        )
        await started.wait()
        display.show_sigint_exit_toast(window_seconds=10)
        consuming.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await consuming
        await asyncio.wait_for(toast_committed.wait(), timeout=1)
        await display.stop()

    asyncio.run(scenario())


def test_replay_keeps_old_bottom_until_transcript_commit(monkeypatch: Any) -> None:
    async def scenario() -> None:
        streams: list[tuple[tuple[str, ...], bool]] = []
        statuses: list[tuple[Any, ...]] = []
        display = TUIDisplay(
            on_stream_update=lambda lines, ended, _style: streams.append((lines, ended)),
            on_status_update=lambda lines, _separator: statuses.append(lines),
        )
        display._renderer.set_stream_renderable(Text("old tail"))
        old_stream = streams[-1]
        entered_commit = asyncio.Event()
        release_commit = asyncio.Event()
        snapshots: list[tuple[str, tuple[tuple[str, ...], bool]]] = []

        async def write_bulk(
            payload: str, *, clear_screen: bool = False, before_write: Callable[[], None] | None = None
        ) -> None:
            assert payload
            entered_commit.set()
            await release_commit.wait()
            snapshots.append(("before", streams[-1]))
            if before_write is not None:
                before_write()
            snapshots.append(("after", streams[-1]))
            display._renderer.set_stream_renderable(Text("later live tail"))
            snapshots.append(("during-drain", streams[-1]))

        monkeypatch.setattr(display_module, "write_scrollback_bulk", write_bulk)
        replay = events.ReplayHistoryEvent(
            session_id="main",
            updated_at=0,
            events=[events.UserMessageEvent(session_id="main", content="new transcript")],
        )
        consuming = asyncio.create_task(display.consume_envelope(make_envelope(replay)))
        await entered_commit.wait()
        assert streams[-1] == old_stream
        assert statuses == []
        release_commit.set()
        await consuming
        assert snapshots[0] == ("before", old_stream)
        assert snapshots[1][0] == "after"
        assert streams[-1] != old_stream
        assert "later live tail" in " ".join(snapshots[2][1][0])
        await display.stop()

    asyncio.run(scenario())


def test_sync_display_change_waits_for_replay_frame(monkeypatch: Any) -> None:
    async def scenario() -> None:
        display = TUIDisplay()
        started = asyncio.Event()
        release = asyncio.Event()
        themes: list[str | None] = []

        async def write_bulk(
            _payload: str, *, clear_screen: bool = False, before_write: Callable[[], None] | None = None
        ) -> None:
            started.set()
            await release.wait()
            if before_write is not None:
                before_write()

        monkeypatch.setattr(display_module, "write_scrollback_bulk", write_bulk)
        monkeypatch.setattr(display._renderer, "set_theme", themes.append)
        replay = events.ReplayHistoryEvent(session_id="main", updated_at=0, events=[])
        consuming = asyncio.create_task(display.consume_envelope(make_envelope(replay)))
        await started.wait()
        display.set_theme("light")
        assert themes == []
        release.set()
        await consuming
        await asyncio.sleep(0)
        assert themes == ["light"]
        await display.stop()

    asyncio.run(scenario())


def test_stop_waits_for_inflight_terminal_commit(monkeypatch: Any) -> None:
    async def scenario() -> None:
        display = TUIDisplay()
        entered_commit = asyncio.Event()
        release_commit = asyncio.Event()
        order: list[str] = []

        async def write_bulk(
            _payload: str, *, clear_screen: bool = False, before_write: Callable[[], None] | None = None
        ) -> None:
            entered_commit.set()
            await release_commit.wait()
            if before_write is not None:
                before_write()
            order.append("commit")

        async def stop_renderer() -> None:
            order.append("stop")

        monkeypatch.setattr(display_module, "write_scrollback_bulk", write_bulk)
        monkeypatch.setattr(display._renderer, "stop", stop_renderer)
        replay = events.ReplayHistoryEvent(session_id="main", updated_at=0, events=[])
        consuming = asyncio.create_task(display.consume_envelope(make_envelope(replay)))
        await entered_commit.wait()
        stopping = asyncio.create_task(display.stop())
        await asyncio.sleep(0)
        assert order == []
        release_commit.set()
        await asyncio.wait_for(asyncio.gather(consuming, stopping), timeout=1)
        assert order == ["commit", "stop"]

    asyncio.run(scenario())


def test_sync_change_cannot_overtake_queued_event(monkeypatch: Any) -> None:
    async def scenario() -> None:
        display = TUIDisplay()
        entered = asyncio.Event()
        release = asyncio.Event()
        order: list[str] = []

        async def execute(commands: list[str]) -> None:
            if commands == ["first"]:
                entered.set()
                await release.wait()
            order.append(commands[0])

        def transition(event: events.Event) -> list[str]:
            assert isinstance(event, events.NoticeEvent)
            return [event.content]

        monkeypatch.setattr(display._machine, "transition", transition)
        monkeypatch.setattr(display._renderer, "execute", execute)
        monkeypatch.setattr(display._renderer, "set_theme", lambda _theme: order.append("theme"))
        first = asyncio.create_task(
            display.consume_envelope(make_envelope(events.NoticeEvent(session_id="main", content="first")))
        )
        await entered.wait()
        second = asyncio.create_task(
            display.consume_envelope(make_envelope(events.NoticeEvent(session_id="main", content="second")))
        )
        await asyncio.sleep(0)
        display.set_theme("light")
        release.set()
        await asyncio.gather(first, second)
        await asyncio.sleep(0)
        assert order == ["first", "second", "theme"]
        await display.stop()

    asyncio.run(scenario())


def test_queued_toast_precedes_immediate_event_without_yield(monkeypatch: Any) -> None:
    async def scenario() -> None:
        display = TUIDisplay()
        order: list[str] = []

        async def execute(commands: list[str]) -> None:
            order.append(commands[0])

        monkeypatch.setattr(display._machine, "show_sigint_exit_toast", lambda: ["toast"])
        monkeypatch.setattr(display._machine, "transition", lambda _event: ["event"])
        monkeypatch.setattr(display._renderer, "execute", execute)
        display.show_sigint_exit_toast(window_seconds=10)
        await display.consume_envelope(make_envelope(events.NoticeEvent(session_id="main", content="later")))
        assert order == ["toast", "event"]
        await display.stop()

    asyncio.run(scenario())


def test_queued_theme_precedes_immediate_event_without_yield(monkeypatch: Any) -> None:
    async def scenario() -> None:
        display = TUIDisplay()
        entered = asyncio.Event()
        release = asyncio.Event()
        order: list[str] = []

        async def execute(commands: list[str]) -> None:
            if commands == ["first"]:
                entered.set()
                await release.wait()
            order.append(commands[0])

        monkeypatch.setattr(display._machine, "transition", lambda event: [event.content])
        monkeypatch.setattr(display._renderer, "execute", execute)
        monkeypatch.setattr(display._renderer, "set_theme", lambda _theme: order.append("theme"))
        first = asyncio.create_task(
            display.consume_envelope(make_envelope(events.NoticeEvent(session_id="main", content="first")))
        )
        await entered.wait()
        display.set_theme("light")
        release.set()
        await display.consume_envelope(make_envelope(events.NoticeEvent(session_id="main", content="second")))
        await first
        assert order == ["first", "theme", "second"]
        await display.stop()

    asyncio.run(scenario())
