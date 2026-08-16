from __future__ import annotations

from pathlib import Path

import pytest

from klaude_code.cli import debug as debug_mod


def test_prepare_debug_logging_disabled() -> None:
    assert debug_mod.prepare_debug_logging(False) == (False, None)


def test_prepare_debug_logging_enables_server_debug(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str, dict[str, object]]] = []

    def _request(
        method: str, path: str, *, json_body: dict[str, object] | None = None, **_kwargs: object
    ) -> tuple[int, object]:
        calls.append((method, path, json_body or {}))
        return 200, {"ok": True, "enabled": True, "log_file": "/tmp/server-debug.log"}

    monkeypatch.setattr("klaude_code.cli.uds_client.request", _request)

    enabled, log_path = debug_mod.prepare_debug_logging(True)

    assert enabled is True
    assert log_path == Path("/tmp/server-debug.log")
    assert calls == [("POST", "/api/server/debug", {"enabled": True})]


def test_prepare_debug_logging_raises_when_server_omits_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "klaude_code.cli.uds_client.request",
        lambda *_args, **_kwargs: (200, {"ok": True, "enabled": True, "log_file": None}),
    )

    with pytest.raises(RuntimeError, match="did not return a debug log file"):
        debug_mod.prepare_debug_logging(True)
