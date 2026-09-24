from __future__ import annotations

import asyncio
from typing import Any, cast

import pytest

from klaude_code.protocol import events, message
from klaude_code.tui.client import server_api
from klaude_code.tui.command.command_abc import Agent
from klaude_code.tui.command.reload_cmd import ReloadCommand


class _Agent:
    session = type("Sess", (), {"id": "sess-1"})()
    profile = None


def _run(body: dict[str, Any] | Exception, monkeypatch: pytest.MonkeyPatch) -> events.NoticeEvent:
    def fake_request() -> dict[str, Any]:
        if isinstance(body, Exception):
            raise body
        return body

    monkeypatch.setattr(server_api, "request_server_reload", fake_request)
    result = asyncio.run(ReloadCommand().run(cast(Agent, _Agent()), message.UserInputPayload(text="/reload")))
    assert result.events is not None and len(result.events) == 1
    notice = result.events[0]
    assert isinstance(notice, events.NoticeEvent)
    return notice


def test_reload_reports_pending_sessions(monkeypatch: pytest.MonkeyPatch) -> None:
    notice = _run(
        {
            "state": "pending",
            "sessions": [{"session_id": "a", "state": "running"}, {"session_id": "b", "state": "queued"}],
            "upgrade": {"action": "upgrade"},
        },
        monkeypatch,
    )
    assert notice.content == "Server will install the pending update and restart once 2 other active sessions finish."
    assert notice.is_error is False


def test_reload_reports_immediate_restart(monkeypatch: pytest.MonkeyPatch) -> None:
    notice = _run({"state": "pending", "sessions": [], "upgrade": {"action": "reload"}}, monkeypatch)
    assert notice.content == "Server is about to restart; this TUI reconnects automatically."


def test_reload_reports_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    notice = _run(RuntimeError("server error 503: unavailable"), monkeypatch)
    assert notice.is_error is True
    assert "server error 503" in notice.content


def test_request_server_reload_posts_when_idle(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str, dict[str, Any] | None]] = []

    def fake_request(method: str, path: str, *, json_body: dict[str, Any] | None = None, timeout: float = 0.0) -> Any:
        del timeout
        calls.append((method, path, json_body))
        return {"state": "pending", "sessions": []}

    monkeypatch.setattr(server_api, "_request", fake_request)
    assert server_api.request_server_reload() == {"state": "pending", "sessions": []}
    assert calls == [("POST", "/api/server/reload", {"force": False, "when": "idle"})]
