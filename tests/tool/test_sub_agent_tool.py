"""Tests for Agent tool plus sub-agent profile basics."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from klaude_code.protocol import tools
from klaude_code.protocol.sub_agent import SubAgentProfile
from klaude_code.tool.agent_tool import AgentTool
from klaude_code.tool.core.context import RunSubtask, TodoContext, ToolContext


def arun(coro: Any) -> Any:
    """Helper to run async coroutines."""
    return asyncio.run(coro)


def _tool_context(*, run_subtask: RunSubtask | None = None, work_dir: Path | None = None) -> ToolContext:
    todo_context = TodoContext(get_todos=lambda: [], set_todos=lambda todos: None)
    return ToolContext(
        file_tracker={},
        todo_context=todo_context,
        session_id="test",
        work_dir=work_dir or Path("/tmp"),
        run_subtask=run_subtask,
    )


def _record_runner(captured: dict[str, Any], *, fail_if_called: bool = False) -> RunSubtask:
    """Runner that records the SubAgentState it receives."""

    async def _runner(
        state: Any, _record_session_id: Any, _register_metadata_getter: Any, _register_progress_getter: Any
    ) -> Any:
        captured["state"] = state
        if fail_if_called:
            raise AssertionError("runner must not be called")

        class _Result:
            task_result = "done"
            session_id = "child-session"
            error = False
            task_metadata = None

        return _Result()

    return _runner


def test_agent_tool_schema(isolated_home: Path) -> None:
    del isolated_home

    schema = AgentTool.schema()

    assert schema.name == tools.AGENT
    assert schema.type == "function"
    assert "description" in schema.parameters["required"]
    assert "prompt" in schema.parameters["required"]
    assert "type" in schema.parameters["properties"]
    assert "model" in schema.parameters["properties"]
    assert "workdir" in schema.parameters["properties"]
    assert "general-purpose" in schema.parameters["properties"]["type"]["enum"]
    assert "resume" not in schema.parameters["properties"]


def test_agent_tool_call_invalid_json() -> None:
    result = arun(AgentTool.call("not valid json", _tool_context()))

    assert result.status == "error"
    assert result.output_text is not None and "Invalid JSON" in result.output_text


def test_agent_tool_call_without_runner() -> None:
    result = arun(AgentTool.call('{"description":"d","prompt":"p"}', _tool_context()))

    assert result.status == "error"
    assert result.output_text is not None and "No sub-agent runner" in result.output_text


def test_agent_tool_call_includes_session_id() -> None:
    captured: dict[str, Any] = {}

    async def _runner(
        state: Any, record_session_id: Any, register_metadata_getter: Any, register_progress_getter: Any
    ) -> Any:
        captured["sub_agent_type"] = state.sub_agent_type
        captured["model"] = state.model
        if callable(record_session_id):
            record_session_id("abc123def456")

        class _Result:
            task_result = "hello"
            session_id = "abc123def456"
            error = False
            task_metadata = None

        return _Result()

    args = '{"type":"finder","description":"d","prompt":"p","model":"gpt-5.4-mini"}'
    result = arun(AgentTool.call(args, _tool_context(run_subtask=_runner)))

    assert captured["sub_agent_type"] == "finder"
    assert captured["model"] == "gpt-5.4-mini"
    assert result.status == "success"
    assert result.output_text == "hello"
    assert result.ui_extra is not None
    assert result.ui_extra.session_id == "abc123def456"


def test_agent_tool_workdir_defaults_to_none(tmp_path: Path) -> None:
    """No workdir means the launcher inherits the parent session's working directory."""
    captured: dict[str, Any] = {}
    args = json.dumps({"type": "finder", "description": "d", "prompt": "p"})

    result = arun(AgentTool.call(args, _tool_context(run_subtask=_record_runner(captured), work_dir=tmp_path)))

    assert result.status == "success"
    assert captured["state"].work_dir is None


def test_agent_tool_workdir_resolves_relative_to_caller(tmp_path: Path) -> None:
    target = tmp_path / "other-repo"
    target.mkdir()
    captured: dict[str, Any] = {}
    args = json.dumps({"type": "finder", "description": "d", "prompt": "p", "workdir": "other-repo"})

    result = arun(AgentTool.call(args, _tool_context(run_subtask=_record_runner(captured), work_dir=tmp_path)))

    assert result.status == "success"
    assert captured["state"].work_dir == str(target.resolve())


def test_agent_tool_workdir_missing_dir_errors(tmp_path: Path) -> None:
    captured: dict[str, Any] = {}
    args = json.dumps({"type": "finder", "description": "d", "prompt": "p", "workdir": str(tmp_path / "missing-repo")})

    result = arun(AgentTool.call(args, _tool_context(run_subtask=_record_runner(captured, fail_if_called=True))))

    assert result.status == "error"
    assert result.output_text is not None and "workdir does not exist" in result.output_text
    assert captured == {}


def test_agent_tool_workdir_file_errors(tmp_path: Path) -> None:
    file_path = tmp_path / "not-a-dir.txt"
    file_path.write_text("x", encoding="utf-8")
    captured: dict[str, Any] = {}
    args = json.dumps({"type": "finder", "description": "d", "prompt": "p", "workdir": str(file_path)})

    result = arun(AgentTool.call(args, _tool_context(run_subtask=_record_runner(captured, fail_if_called=True))))

    assert result.status == "error"
    assert result.output_text is not None and "workdir is not a directory" in result.output_text
    assert captured == {}


def test_agent_tool_workdir_rejected_for_fork_context(tmp_path: Path) -> None:
    captured: dict[str, Any] = {}
    args = json.dumps(
        {"type": "general-purpose-fork-context", "description": "d", "prompt": "p", "workdir": str(tmp_path)}
    )

    result = arun(AgentTool.call(args, _tool_context(run_subtask=_record_runner(captured, fail_if_called=True))))

    assert result.status == "error"
    assert result.output_text is not None and "fork-context" in result.output_text
    assert captured == {}


class TestSubAgentProfile:
    def test_default_values(self) -> None:
        profile = SubAgentProfile(name="Minimal")

        assert profile.prompt_file == ""
        assert profile.tool_set == ()
        assert profile.active_form == ""
        assert profile.invoker_summary == ""


class TestSubAgentRegistration:
    def test_is_sub_agent_tool(self) -> None:
        from klaude_code.protocol.sub_agent import is_sub_agent_tool

        assert is_sub_agent_tool(tools.AGENT) is True
        assert is_sub_agent_tool("Finder") is False

    def test_get_sub_agent_profile(self) -> None:
        from klaude_code.protocol.sub_agent import get_sub_agent_profile

        profile = get_sub_agent_profile("general-purpose")
        assert profile.name == "general-purpose"
        assert profile.active_form == "Tasking"

    def test_get_sub_agent_profile_not_found(self) -> None:
        from klaude_code.protocol.sub_agent import get_sub_agent_profile

        with pytest.raises(KeyError) as exc_info:
            get_sub_agent_profile("NonExistent")
        assert "Unknown sub agent type" in str(exc_info.value)

    def test_iter_sub_agent_profiles(self) -> None:
        from klaude_code.protocol.sub_agent import iter_sub_agent_profiles

        profiles = iter_sub_agent_profiles()
        assert len(profiles) > 0
        names = {p.name for p in profiles}
        assert {"general-purpose", "finder"}.issubset(names)
