from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

from klaude_code.protocol import message
from klaude_code.tui.command.web_cmd import WebCommand


def arun(coro: Any) -> Any:
    return asyncio.run(coro)

def _agent() -> Any:
    return SimpleNamespace(session=SimpleNamespace(id="s1"))

def test_web_command_requests_web_mode_with_defaults() -> None:
    result = arun(WebCommand().run(_agent(), message.UserInputPayload(text="")))

    assert result.web_mode_request is not None
    assert result.web_mode_request.host == "127.0.0.1"
    assert result.web_mode_request.port == 8765
    assert result.web_mode_request.no_open is False
    assert result.web_mode_request.debug is None
    assert result.events is not None
    assert result.events[0].content == "Switching to web mode..."

def test_web_command_parses_flags() -> None:
    result = arun(
        WebCommand().run(
            _agent(),
            message.UserInputPayload(text="--host 0.0.0.0 --port 9000 --no-open --debug"),
        )
    )

    assert result.web_mode_request is not None
    assert result.web_mode_request.host == "0.0.0.0"
    assert result.web_mode_request.port == 9000
    assert result.web_mode_request.no_open is True
    assert result.web_mode_request.debug is True

def test_web_command_help_does_not_switch_modes() -> None:
    result = arun(WebCommand().run(_agent(), message.UserInputPayload(text="--help")))

    assert result.web_mode_request is None
    assert result.events is not None
    assert result.events[0].is_error is False
    assert "Usage: /web" in result.events[0].content

def test_web_command_invalid_args_show_error() -> None:
    result = arun(WebCommand().run(_agent(), message.UserInputPayload(text="--port nope")))

    assert result.web_mode_request is None
    assert result.events is not None
    assert result.events[0].is_error is True
    assert "Invalid /web arguments" in result.events[0].content
