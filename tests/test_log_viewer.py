from __future__ import annotations

import errno
import os
from pathlib import Path
from typing import Any, cast

import pytest

from klaude_code.app import log_viewer


class _DummyServer:
    def serve_forever(self) -> None:  # pragma: no cover
        raise NotImplementedError


def test_create_server_with_fallback_uses_start_port(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []

    def _fake_http_server(address: tuple[str, int], _handler: Any) -> _DummyServer:
        calls.append(address[1])
        return _DummyServer()

    monkeypatch.setattr(log_viewer, "HTTPServer", cast(Any, _fake_http_server))

    _server, port = log_viewer._create_server_with_fallback(8765)  # pyright: ignore[reportPrivateUsage]

    assert port == 8765
    assert calls == [8765]


def test_create_server_with_fallback_increments_when_port_in_use(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []

    def _fake_http_server(address: tuple[str, int], _handler: Any) -> _DummyServer:
        port = address[1]
        calls.append(port)
        if port <= 8766:
            raise OSError(errno.EADDRINUSE, "Address already in use")
        return _DummyServer()

    monkeypatch.setattr(log_viewer, "HTTPServer", cast(Any, _fake_http_server))

    _server, port = log_viewer._create_server_with_fallback(8765)  # pyright: ignore[reportPrivateUsage]

    assert port == 8767
    assert calls == [8765, 8766, 8767]


def test_create_server_with_fallback_raises_non_address_in_use_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake_http_server(_address: tuple[str, int], _handler: Any) -> _DummyServer:
        raise OSError(errno.EACCES, "Permission denied")

    monkeypatch.setattr(log_viewer, "HTTPServer", cast(Any, _fake_http_server))

    with pytest.raises(OSError, match="Permission denied"):
        log_viewer._create_server_with_fallback(8765)  # pyright: ignore[reportPrivateUsage]


def test_list_log_files_sorts_by_mtime_desc(tmp_path: Path) -> None:
    log_dir = tmp_path / "logs"
    first = log_dir / "2026-02-27" / "100000-1.log"
    second = log_dir / "2026-02-28" / "110000-2.log"
    first.parent.mkdir(parents=True)
    second.parent.mkdir(parents=True)
    first.write_text("first")
    second.write_text("second")
    os.utime(first, (1_700_000_000, 1_700_000_000))
    os.utime(second, (1_800_000_000, 1_800_000_000))

    files = log_viewer._list_log_files(log_dir.resolve())  # pyright: ignore[reportPrivateUsage]

    assert [file["relative_path"] for file in files] == ["2026-02-28/110000-2.log", "2026-02-27/100000-1.log"]


def test_is_path_within_checks_directory_boundary(tmp_path: Path) -> None:
    root = tmp_path / "logs-root"
    root.mkdir()
    inside = root / "2026-02-28" / "x.log"
    outside = root.parent / "other" / "x.log"

    assert log_viewer._is_path_within(inside, root) is True  # pyright: ignore[reportPrivateUsage]
    assert log_viewer._is_path_within(outside, root) is False  # pyright: ignore[reportPrivateUsage]
