"""Tests for `klaude server config-reload`."""

from __future__ import annotations

from typing import Any

import pytest
import typer

import klaude_code.cli.server_cmd as server_cmd
from klaude_code.cli.uds_client import ServerNotRunningError


def _run(monkeypatch: pytest.MonkeyPatch, response: Any) -> None:
    def fake_request(method: str, path: str, json_body: dict[str, Any] | None = None, timeout: float = 10.0) -> Any:
        del method, json_body, timeout
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(server_cmd, "_request", fake_request)
    server_cmd.config_reload_command()


def test_reload_command_reports_the_revision(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _run(monkeypatch, (200, {"ok": True, "pid": 1, "revision": 7}))

    assert "revision 7" in capsys.readouterr().out


def test_reload_command_prints_the_servers_answer(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """An older server without the field still reports success."""
    _run(monkeypatch, (200, {"ok": True, "pid": 1}))

    assert "reloaded its config" in capsys.readouterr().out


def test_reload_command_fails_when_the_server_is_down(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(typer.Exit) as exc_info:
        _run(monkeypatch, ServerNotRunningError("no socket"))

    assert exc_info.value.exit_code == 1


def test_reload_command_fails_on_a_rejected_config(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(typer.Exit) as exc_info:
        _run(monkeypatch, (400, {"detail": "Invalid config file"}))

    assert exc_info.value.exit_code == 1
    assert "Unexpected server response (400)" in capsys.readouterr().out
