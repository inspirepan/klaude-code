from __future__ import annotations

import asyncio
import contextlib
import threading
import time

import pytest

from klaude_code.log import DebugType
from klaude_code.protocol import events
from klaude_code.tui import diagnostics
from klaude_code.tui.client.local import LocalRuntimeClient
from klaude_code.tui.display import TUIDisplay

from .test_transcript_toggle import make_envelope


def test_watchdog_samples_during_block_once_and_stops_with_display(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("klaude_code.log._debug_enabled", True)
    captured = threading.Event()
    records: list[str] = []

    def record(text: str, *, debug_type: DebugType) -> None:
        assert debug_type == DebugType.EXECUTION
        records.append(text)
        captured.set()

    monkeypatch.setattr(diagnostics, "log_debug", record)

    def blocking_loop_function() -> None:
        local_secret = "DO_NOT_LOG_THIS_LOCAL_OR_SOURCE"
        assert captured.wait(timeout=3), local_secret
        # Stay blocked across multiple sampler ticks after the first capture.
        time.sleep(0.4)

    async def run() -> None:
        display = TUIDisplay()
        display._create_bg_task(display._watch_event_loop_stalls(interval=0.02, threshold=0.2))
        try:
            await asyncio.sleep(0.4)
            assert records == []
            sampling_threads = [thread for thread in threading.enumerate() if thread.name == "tui-stall-sampler"]
            assert len(sampling_threads) == 1
            assert sampling_threads[0].daemon
            blocking_loop_function()
            assert len(records) == 1
            assert "in blocking_loop_function" in records[0]
            assert "DO_NOT_LOG_THIS_LOCAL_OR_SOURCE" not in records[0]
            assert "captured.wait" not in records[0]
            await asyncio.sleep(0.1)
            captured.clear()
            blocking_loop_function()
            assert len(records) == 2
        finally:
            await display.stop()
        assert not sampling_threads[0].is_alive()
        time.sleep(0.4)
        assert len(records) == 2

    asyncio.run(run())


def test_watchdog_without_debug_does_not_create_sampler(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("klaude_code.log._debug_enabled", False)

    def unexpected_sampler(**_kwargs: float) -> None:
        pytest.fail("non-debug watchdog created a sampler")

    monkeypatch.setattr("klaude_code.tui.display.LoopStallSampler", unexpected_sampler)

    async def run() -> None:
        task = asyncio.create_task(TUIDisplay._watch_event_loop_stalls(interval=0.01, threshold=0.02))
        try:
            await asyncio.sleep(0.05)
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    asyncio.run(run())


def test_event_diagnostics_cover_queue_and_render_without_payloads(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("klaude_code.log._debug_enabled", True)
    records: list[str] = []
    clock = [0.0]
    monkeypatch.setattr(diagnostics, "monotonic", lambda: clock[0])

    def record(text: str, *, debug_type: DebugType) -> None:
        assert debug_type == DebugType.EXECUTION
        records.append(text)

    monkeypatch.setattr(diagnostics, "log_debug", record)

    async def run() -> None:
        display = TUIDisplay()
        client = LocalRuntimeClient("main", on_envelope=display.consume_envelope)
        refresh_seconds = 0.05

        def refresh() -> None:
            clock[0] += refresh_seconds

        monkeypatch.setattr(client, "_refresh_info", refresh)
        envelope = make_envelope(events.UserMessageEvent(session_id="main", content="PRIVATE_MESSAGE"))
        await client.consume_envelope(envelope)
        assert not any("refresh_info" in record for record in records)
        refresh_seconds = 0.15
        envelope = envelope.model_copy(update={"event_seq": 2})
        await client.consume_envelope(envelope)
        assert any("local.refresh_info.end session=main seq=2" in record for record in records)
        assert not any("display.consume" in record for record in records)
        client.start_display()
        try:
            await client.wait_for_display_idle()
            for seq in (1, 2):
                stages = [record.split()[1] for record in records if f"seq={seq} " in record]
                assert stages == [
                    "local.consume",
                    *(["local.refresh_info.end"] if seq == 2 else []),
                    "local.display_enqueue",
                    "local.display_dequeued",
                    "display.wait",
                    "display.consume.begin",
                    "display.consume.end",
                ]
            assert all("PRIVATE_MESSAGE" not in record for record in records)
            records.clear()
            monkeypatch.setattr("klaude_code.log._debug_enabled", False)
            await client.consume_envelope(envelope)
            await client.wait_for_display_idle()
            assert records == []
        finally:
            assert client._display_task is not None
            client._display_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await client._display_task
            await display.stop()

    asyncio.run(run())
