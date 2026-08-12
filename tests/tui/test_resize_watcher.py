from __future__ import annotations

import asyncio
from typing import Any

from klaude_code.tui.input.resize_watcher import ResizeWatcher


def _patch_width(monkeypatch: Any, width: dict[str, int]) -> None:
    monkeypatch.setattr(ResizeWatcher, "_current_width", staticmethod(lambda: width["value"]))


def test_resize_burst_fires_once_after_settle(monkeypatch: Any) -> None:
    async def _test() -> None:
        width = {"value": 100}
        _patch_width(monkeypatch, width)
        fired: list[int] = []
        watcher = ResizeWatcher(lambda: fired.append(width["value"]), settle_seconds=0.01)

        width["value"] = 90
        watcher.notify_resize()
        width["value"] = 80
        watcher.notify_resize()
        width["value"] = 70
        watcher.notify_resize()
        assert fired == []

        await asyncio.sleep(0.05)
        assert fired == [70]

    asyncio.run(_test())


def test_height_only_resize_does_not_fire(monkeypatch: Any) -> None:
    async def _test() -> None:
        width = {"value": 100}
        _patch_width(monkeypatch, width)
        fired: list[int] = []
        watcher = ResizeWatcher(lambda: fired.append(width["value"]), settle_seconds=0.01)

        watcher.notify_resize()
        await asyncio.sleep(0.05)
        assert fired == []

    asyncio.run(_test())


def test_drag_back_to_original_width_does_not_fire(monkeypatch: Any) -> None:
    async def _test() -> None:
        width = {"value": 100}
        _patch_width(monkeypatch, width)
        fired: list[int] = []
        watcher = ResizeWatcher(lambda: fired.append(width["value"]), settle_seconds=0.01)

        width["value"] = 60
        watcher.notify_resize()
        width["value"] = 100
        watcher.notify_resize()
        await asyncio.sleep(0.05)
        assert fired == []

    asyncio.run(_test())


def test_each_settled_width_change_fires(monkeypatch: Any) -> None:
    async def _test() -> None:
        width = {"value": 100}
        _patch_width(monkeypatch, width)
        fired: list[int] = []
        watcher = ResizeWatcher(lambda: fired.append(width["value"]), settle_seconds=0.01)

        width["value"] = 80
        watcher.notify_resize()
        await asyncio.sleep(0.05)
        width["value"] = 120
        watcher.notify_resize()
        await asyncio.sleep(0.05)
        assert fired == [80, 120]

    asyncio.run(_test())


def test_cancel_suppresses_pending_settle(monkeypatch: Any) -> None:
    async def _test() -> None:
        width = {"value": 100}
        _patch_width(monkeypatch, width)
        fired: list[int] = []
        watcher = ResizeWatcher(lambda: fired.append(width["value"]), settle_seconds=0.01)

        width["value"] = 80
        watcher.notify_resize()
        watcher.cancel()
        await asyncio.sleep(0.05)
        assert fired == []

    asyncio.run(_test())


def test_width_change_repaints_without_recent_activity(monkeypatch: Any) -> None:
    async def _test() -> None:
        width = {"value": 100}
        _patch_width(monkeypatch, width)
        fired: list[int] = []
        watcher = ResizeWatcher(lambda: fired.append(width["value"]), settle_seconds=0.01)

        width["value"] = 80
        watcher.notify_resize()
        await asyncio.sleep(0.05)
        assert fired == [80]

    asyncio.run(_test())
