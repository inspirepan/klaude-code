from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from klaude_code.protocol import llm_param, message
from klaude_code.session.session import Session
from klaude_code.tui.command import export_session_cmd
from klaude_code.tui.command.export_session_cmd import ExportSessionCommand

pytestmark = pytest.mark.usefixtures("isolated_home")

class _DummyAgent:
    def __init__(self, session: Session, *, system_prompt: str = "", tools: list[llm_param.ToolSchema] | None = None):
        self.session = session
        self.profile = _DummyProfile(system_prompt=system_prompt, tools=tools or [])

    def get_llm_client(self) -> Any:  # pragma: no cover
        return self.profile.llm_client

class _DummyProfile:
    def __init__(self, *, system_prompt: str, tools: list[llm_param.ToolSchema]):
        self._llm_client: Any = object()
        self._system_prompt = system_prompt
        self._tools = tools

    @property
    def llm_client(self) -> Any:
        return self._llm_client

    @property
    def system_prompt(self) -> str | None:
        return self._system_prompt

    @property
    def tools(self) -> list[llm_param.ToolSchema]:
        return self._tools

def arun(coro: Any) -> Any:
    return asyncio.run(coro)

def test_export_session_command_writes_html_with_prompt_and_tools(tmp_path: Path) -> None:
    session = Session.create(work_dir=tmp_path)
    session.title = "Export Demo"
    session.conversation_history = [
        message.UserMessage(parts=message.text_parts_from_str("hello **world**")),
        message.AssistantMessage(
            parts=[
                message.ThinkingTextPart(text="check repo state"),
                message.TextPart(text="Implemented the export command."),
                message.ToolCallPart(call_id="call_1", tool_name="Bash", arguments_json='{"command":"pwd"}'),
            ]
        ),
        message.ToolResultMessage(call_id="call_1", tool_name="Bash", status="success", output_text=str(tmp_path)),
        message.DeveloperMessage(parts=message.text_parts_from_str("<system-reminder>Checkpoint 1</system-reminder>")),
    ]
    tools = [
        llm_param.ToolSchema(
            name="Bash",
            type="function",
            description="Run shell commands",
            parameters={
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Command to run"},
                    "timeout_ms": {"type": "integer", "description": "Timeout in milliseconds"},
                },
                "required": ["command"],
            },
        )
    ]
    open_calls: list[list[str]] = []

    def _run_open(args: list[str], *, check: bool) -> None:
        open_calls.append(args)
        assert check is False

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(export_session_cmd.sys, "platform", "darwin")
    monkeypatch.setattr(export_session_cmd.subprocess, "run", _run_open)

    try:
        result = arun(
            ExportSessionCommand().run(
                _DummyAgent(session, system_prompt="You are a terminal coding agent.", tools=tools),
                message.UserInputPayload(text="exported/session-view"),
            )
        )
    finally:
        monkeypatch.undo()

    assert result.events is not None
    assert result.events[0].is_error is False

    output_path = tmp_path / "exported" / "session-view.html"
    assert open_calls == [["open", str(output_path.resolve())]]
    assert output_path.exists() is True
    html_text = output_path.read_text(encoding="utf-8")
    assert "You are a terminal coding agent." in html_text
    assert "Available Tools" in html_text
    assert "Run shell commands" in html_text
    assert "Implemented the export command." in html_text
    assert "Checkpoint 1" in html_text
    assert "call_1" in html_text
    assert "Opened in the default app." in result.events[0].content

def test_export_session_command_rejects_empty_session(tmp_path: Path) -> None:
    session = Session.create(work_dir=tmp_path)

    result = arun(
        ExportSessionCommand().run(
            _DummyAgent(session),
            message.UserInputPayload(text=""),
        )
    )

    assert result.events is not None
    assert result.events[0].is_error is True
    assert "Nothing to export yet" in result.events[0].content
