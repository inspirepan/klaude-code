"""`klaude trace`: read the server's web port and hand the URL to a browser."""

from __future__ import annotations

from typing import Any

import pytest
from typer.testing import CliRunner

import klaude_code.cli.uds_client as uds_client
from klaude_code.cli.main import app


@pytest.fixture
def opened_urls(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    urls: list[str] = []

    def _open(url: str, *_args: object, **_kwargs: object) -> bool:
        urls.append(url)
        return True

    monkeypatch.setattr("webbrowser.open", _open)
    return urls


def _stub_status(monkeypatch: pytest.MonkeyPatch, body: Any, status_code: int = 200) -> list[str]:
    """Answer the CLI's status request without touching a real server."""

    calls: list[str] = []

    def _request(method: str, path: str, **_kwargs: object) -> tuple[int, Any]:
        calls.append(f"{method} {path}")
        return status_code, body

    monkeypatch.setattr(uds_client, "request_with_autostart", _request)
    return calls


def test_trace_opens_the_browser_at_the_reported_url(monkeypatch: pytest.MonkeyPatch, opened_urls: list[str]) -> None:
    calls = _stub_status(monkeypatch, {"web_port": 8766, "web_url": "http://127.0.0.1:8766"})

    result = CliRunner().invoke(app, ["trace"])

    assert result.exit_code == 0, result.output
    assert calls == ["GET /api/server/status"]
    assert opened_urls == ["http://127.0.0.1:8766"]
    assert "http://127.0.0.1:8766" in result.output


def test_trace_falls_back_to_the_port_when_url_is_absent(monkeypatch: pytest.MonkeyPatch, opened_urls: list[str]) -> None:
    _stub_status(monkeypatch, {"web_port": 8765})

    result = CliRunner().invoke(app, ["trace"])

    assert result.exit_code == 0, result.output
    assert opened_urls == ["http://127.0.0.1:8765"]


def test_trace_no_open_only_prints(monkeypatch: pytest.MonkeyPatch, opened_urls: list[str]) -> None:
    _stub_status(monkeypatch, {"web_port": 8765, "web_url": "http://127.0.0.1:8765"})

    result = CliRunner().invoke(app, ["trace", "--no-open"])

    assert result.exit_code == 0, result.output
    assert opened_urls == []
    assert "http://127.0.0.1:8765" in result.output


def test_trace_print_url_emits_only_the_url(monkeypatch: pytest.MonkeyPatch, opened_urls: list[str]) -> None:
    _stub_status(monkeypatch, {"web_port": 8765, "web_url": "http://127.0.0.1:8765"})

    result = CliRunner().invoke(app, ["trace", "--print-url"])

    assert result.exit_code == 0, result.output
    assert opened_urls == []
    assert result.output.strip() == "http://127.0.0.1:8765"


def test_trace_reports_a_server_without_a_web_port(monkeypatch: pytest.MonkeyPatch, opened_urls: list[str]) -> None:
    _stub_status(monkeypatch, {"web_port": None, "web_url": None})

    result = CliRunner().invoke(app, ["trace"])

    assert result.exit_code == 1
    assert opened_urls == []
    assert "no web port" in result.output
    assert "klaude server logs" in result.output


def test_trace_reports_an_unreachable_server(monkeypatch: pytest.MonkeyPatch, opened_urls: list[str]) -> None:
    def _request(*_args: object, **_kwargs: object) -> tuple[int, Any]:
        raise uds_client.ServerNotRunningError("/tmp/server.sock")

    monkeypatch.setattr(uds_client, "request_with_autostart", _request)

    result = CliRunner().invoke(app, ["trace"])

    assert result.exit_code == 1
    assert opened_urls == []
    assert "could not reach the klaude server" in result.output


def test_trace_is_listed_in_the_top_level_help() -> None:
    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "trace " in result.output
    assert "browser viewer" in result.output
