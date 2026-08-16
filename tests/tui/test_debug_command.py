from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from klaude_code.protocol import message
from klaude_code.session.session import Session
from klaude_code.tui.command import debug_cmd

pytestmark = pytest.mark.usefixtures("isolated_home")


class _DummyAgent:
    def __init__(self, session: Session):
        self.session = session
        self.profile = None

    def get_llm_client(self) -> Any:  # pragma: no cover
        raise NotImplementedError


def arun(coro: Any) -> Any:
    return asyncio.run(coro)


def test_debug_command_starts_log_viewer(monkeypatch: pytest.MonkeyPatch) -> None:
    session = Session.create(work_dir=Path.cwd())
    viewer_paths: list[Path] = []

    def _enable_server_debug_logging() -> Path:
        return Path("/tmp/klaude-debug.log")

    def _start_log_viewer(log_path: Path) -> str:
        viewer_paths.append(log_path)
        return "http://127.0.0.1:9999/?log=/tmp/klaude-debug.log"

    monkeypatch.setattr(debug_cmd, "enable_server_debug_logging", _enable_server_debug_logging)
    monkeypatch.setattr(debug_cmd, "start_log_viewer", _start_log_viewer)

    cmd = debug_cmd.DebugCommand()
    result = arun(cmd.run(_DummyAgent(session), message.UserInputPayload(text="")))

    assert viewer_paths == [Path("/tmp/klaude-debug.log")]
    assert result.events is not None
    content = result.events[0].content
    assert "Log file: /tmp/klaude-debug.log" in content
    assert "Log viewer: http://127.0.0.1:9999/?log=/tmp/klaude-debug.log" in content


def test_debug_command_reports_server_error(monkeypatch: pytest.MonkeyPatch) -> None:
    session = Session.create(work_dir=Path.cwd())

    def _enable_server_debug_logging() -> Path:
        raise RuntimeError("server error 503: Server lifecycle is not available")

    monkeypatch.setattr(debug_cmd, "enable_server_debug_logging", _enable_server_debug_logging)

    cmd = debug_cmd.DebugCommand()
    result = arun(cmd.run(_DummyAgent(session), message.UserInputPayload(text="")))

    assert result.events is not None
    assert result.events[0].is_error is True
    assert "Failed to enable debug logging" in result.events[0].content
