# pyright: reportPrivateUsage=false
"""Tests for Task and ImageGen tools plus sub-agent profile basics."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from klaude_code.core.tool.context import RunSubtask, TodoContext, ToolContext
from klaude_code.core.tool.sub_agent.image_gen import ImageGenTool
from klaude_code.core.tool.sub_agent.task import TaskTool
from klaude_code.protocol import tools
from klaude_code.protocol.sub_agent import SubAgentProfile, _default_prompt_builder


def arun(coro: Any) -> Any:
    """Helper to run async coroutines."""
    return asyncio.run(coro)


def _tool_context(*, run_subtask: RunSubtask | None = None) -> ToolContext:
    todo_context = TodoContext(get_todos=lambda: [], set_todos=lambda todos: None)
    return ToolContext(file_tracker={}, todo_context=todo_context, session_id="test", run_subtask=run_subtask)


def test_task_tool_schema() -> None:
    schema = TaskTool.schema()

    assert schema.name == tools.TASK
    assert schema.type == "function"
    assert "description" in schema.parameters["required"]
    assert "prompt" in schema.parameters["required"]
    assert "type" in schema.parameters["properties"]
    assert "general-purpose" in schema.parameters["properties"]["type"]["enum"]


def test_image_gen_tool_schema() -> None:
    schema = ImageGenTool.schema()

    assert schema.name == tools.IMAGE_GEN
    assert schema.type == "function"
    assert "prompt" in schema.parameters["required"]


def test_task_tool_call_invalid_json() -> None:
    result = arun(TaskTool.call("not valid json", _tool_context()))

    assert result.status == "error"
    assert result.output_text is not None and "Invalid JSON" in result.output_text


def test_task_tool_call_without_runner() -> None:
    result = arun(TaskTool.call('{"description":"d","prompt":"p"}', _tool_context()))

    assert result.status == "error"
    assert result.output_text is not None and "No subtask runner" in result.output_text


def test_task_tool_call_includes_session_id() -> None:
    captured: dict[str, Any] = {}

    async def _runner(
        state: Any, record_session_id: Any, register_metadata_getter: Any, register_progress_getter: Any
    ) -> Any:
        captured["sub_agent_type"] = state.sub_agent_type
        if callable(record_session_id):
            record_session_id("abc123def456")

        class _Result:
            task_result = "hello"
            session_id = "abc123def456"
            error = False
            task_metadata = None

        return _Result()

    args = '{"type":"explore","description":"d","prompt":"p"}'
    result = arun(TaskTool.call(args, _tool_context(run_subtask=_runner)))

    assert captured["sub_agent_type"] == "Explore"
    assert result.status == "success"
    assert result.output_text == "hello"
    assert result.ui_extra is not None
    assert result.ui_extra.session_id == "abc123def456"


class TestSubAgentProfile:
    def test_default_values(self) -> None:
        profile = SubAgentProfile(name="Minimal")

        assert profile.prompt_file == ""
        assert profile.tool_set == ()
        assert profile.active_form == ""
        assert profile.invoker_type is None
        assert profile.invoker_summary == ""
        assert profile.standalone_tool is False
        assert profile.availability_requirement is None

    def test_custom_prompt_builder(self) -> None:
        def custom_builder(args: dict[str, Any]) -> str:
            task = args.get("task", "")
            context = args.get("context", "")
            return f"Task: {task}\nContext: {context}"

        profile = SubAgentProfile(name="CustomBuilder", prompt_builder=custom_builder)
        result = profile.prompt_builder({"task": "Do something", "context": "Important"})

        assert "Task: Do something" in result
        assert "Context: Important" in result


class TestPromptBuilder:
    def test_default_prompt_builder(self) -> None:
        result = _default_prompt_builder({"prompt": "Hello world"})
        assert result == "Hello world"

    def test_default_prompt_builder_missing_prompt(self) -> None:
        result = _default_prompt_builder({})
        assert result == ""


class TestSubAgentRegistration:
    def test_is_sub_agent_tool(self) -> None:
        from klaude_code.protocol.sub_agent import is_sub_agent_tool

        assert is_sub_agent_tool(tools.TASK) is True
        assert is_sub_agent_tool(tools.IMAGE_GEN) is True
        assert is_sub_agent_tool("Explore") is False

    def test_get_sub_agent_profile(self) -> None:
        from klaude_code.protocol.sub_agent import get_sub_agent_profile

        profile = get_sub_agent_profile("Task")
        assert profile.name == "Task"
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
        assert {"Task", "Explore", "Web", "ImageGen"}.issubset(names)
