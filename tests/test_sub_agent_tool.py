# pyright: reportPrivateUsage=false
"""Tests for sub_agent_tool module."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from klaude_code.core.tool.sub_agent_tool import SubAgentTool
from klaude_code.protocol.sub_agent import SubAgentProfile


def arun(coro: Any) -> Any:
    """Helper to run async coroutines."""
    return asyncio.run(coro)


class TestSubAgentToolForProfile:
    """Test SubAgentTool.for_profile class method."""

    def test_creates_tool_class(self):
        """Test creating a tool class from profile."""
        profile = SubAgentProfile(
            name="TestAgent",
            description="A test agent",
            parameters={"type": "object", "properties": {}},
        )
        tool_class = SubAgentTool.for_profile(profile)

        assert tool_class.__name__ == "TestAgentTool"
        assert issubclass(tool_class, SubAgentTool)
        assert tool_class._profile is profile

    def test_created_class_has_correct_schema(self):
        """Test that created class returns correct schema."""
        profile = SubAgentProfile(
            name="CustomAgent",
            description="Custom agent description",
            parameters={
                "type": "object",
                "properties": {
                    "prompt": {"type": "string"},
                },
                "required": ["prompt"],
            },
        )
        tool_class = SubAgentTool.for_profile(profile)
        schema = tool_class.schema()

        assert schema.name == "CustomAgent"
        assert schema.description == "Custom agent description"
        assert schema.parameters["properties"]["prompt"]["type"] == "string"

    def test_multiple_profiles_create_distinct_classes(self):
        """Test that different profiles create distinct tool classes."""
        profile1 = SubAgentProfile(name="Agent1", description="First agent", parameters={})
        profile2 = SubAgentProfile(name="Agent2", description="Second agent", parameters={})

        class1 = SubAgentTool.for_profile(profile1)
        class2 = SubAgentTool.for_profile(profile2)

        assert class1 is not class2
        assert class1._profile is not class2._profile
        assert class1.schema().name == "Agent1"
        assert class2.schema().name == "Agent2"


class TestSubAgentToolSchema:
    """Test SubAgentTool.schema method."""

    def test_schema_returns_tool_schema(self):
        """Test schema method returns proper ToolSchema."""
        profile = SubAgentProfile(
            name="SchemaTest",
            description="Test description",
            parameters={
                "type": "object",
                "properties": {
                    "input": {"type": "string", "description": "Input text"},
                },
                "required": ["input"],
            },
        )
        tool_class = SubAgentTool.for_profile(profile)
        schema = tool_class.schema()

        assert schema.type == "function"
        assert schema.name == "SchemaTest"
        assert schema.description == "Test description"
        assert "input" in schema.parameters["properties"]


class TestSubAgentToolCall:
    """Test SubAgentTool.call method."""

    def test_call_with_invalid_json(self):
        """Test call with invalid JSON arguments."""
        profile = SubAgentProfile(
            name="TestAgent",
            description="Test",
            parameters={},
        )
        tool_class = SubAgentTool.for_profile(profile)
        result = arun(tool_class.call("not valid json"))

        assert result.status == "error"
        assert result.output is not None and "Invalid JSON" in result.output

    def test_call_without_runner(self):
        """Test call when no subtask runner is available."""
        profile = SubAgentProfile(
            name="TestAgent",
            description="Test",
            parameters={},
        )
        tool_class = SubAgentTool.for_profile(profile)
        result = arun(tool_class.call('{"prompt": "test"}'))

        assert result.status == "error"
        assert result.output is not None and "No subtask runner" in result.output

    def test_call_appends_agent_id_when_session_returned(self):
        """Tool result should include agentId footer when session_id is present."""

        async def _runner(state: Any) -> Any:
            class _Result:
                task_result = "hello"
                session_id = "abc123def456"
                error = False
                task_metadata = None

            return _Result()

        from klaude_code.core.tool.tool_context import current_run_subtask_callback

        profile = SubAgentProfile(
            name="TestAgent",
            description="Test",
            parameters={"type": "object", "properties": {"prompt": {"type": "string"}}},
        )
        tool_class = SubAgentTool.for_profile(profile)
        token = current_run_subtask_callback.set(_runner)  # type: ignore[arg-type]
        try:
            result = arun(tool_class.call('{"prompt": "test"}'))
        finally:
            current_run_subtask_callback.reset(token)

        assert result.status == "success"
        assert result.output is not None
        assert "agentId: abc123def456" in result.output


class TestSubAgentProfile:
    """Test SubAgentProfile dataclass."""

    def test_default_values(self):
        """Test profile default values."""
        profile = SubAgentProfile(
            name="Minimal",
            description="Minimal profile",
        )

        assert profile.parameters == {}
        assert profile.tool_set == ()
        assert profile.active_form == ""
        assert profile.enabled_by_default is True
        assert profile.show_in_main_agent is True
        assert profile.target_model_filter is None

    def test_enabled_for_model_default_true(self):
        """Test enabled_for_model returns True by default."""
        profile = SubAgentProfile(name="Test", description="Test")
        assert profile.enabled_for_model("gpt-4") is True
        assert profile.enabled_for_model(None) is True

    def test_enabled_for_model_disabled_by_default(self):
        """Test enabled_for_model returns False when disabled."""
        profile = SubAgentProfile(
            name="Test",
            description="Test",
            enabled_by_default=False,
        )
        assert profile.enabled_for_model("gpt-4") is False

    def test_enabled_for_model_with_filter(self):
        """Test enabled_for_model with model filter."""
        # Filter that excludes gpt-5
        profile = SubAgentProfile(
            name="Test",
            description="Test",
            target_model_filter=lambda model: "gpt-5" not in model,
        )

        assert profile.enabled_for_model("gpt-4") is True
        assert profile.enabled_for_model("gpt-5-turbo") is False
        assert profile.enabled_for_model(None) is True  # None model bypasses filter

    def test_full_profile_creation(self):
        """Test creating profile with all fields."""
        profile = SubAgentProfile(
            name="FullAgent",
            description="Full agent with all options",
            parameters={
                "type": "object",
                "properties": {"prompt": {"type": "string"}},
            },
            tool_set=("Read", "Bash", "Edit"),
            active_form="Working",
            enabled_by_default=True,
            show_in_main_agent=True,
            target_model_filter=lambda m: True,
        )

        assert profile.name == "FullAgent"
        assert profile.tool_set == ("Read", "Bash", "Edit")
        assert profile.active_form == "Working"


class TestPromptBuilder:
    """Test prompt builder functionality."""

    def test_default_prompt_builder(self):
        """Test default prompt builder returns prompt field."""
        from klaude_code.protocol.sub_agent import _default_prompt_builder

        result = _default_prompt_builder({"prompt": "Hello world"})
        assert result == "Hello world"

    def test_default_prompt_builder_missing_prompt(self):
        """Test default prompt builder with missing prompt."""
        from klaude_code.protocol.sub_agent import _default_prompt_builder

        result = _default_prompt_builder({})
        assert result == ""

    def test_custom_prompt_builder(self):
        """Test custom prompt builder in profile."""

        def custom_builder(args: dict[str, Any]) -> str:
            task = args.get("task", "")
            context = args.get("context", "")
            return f"Task: {task}\nContext: {context}"

        profile = SubAgentProfile(
            name="CustomBuilder",
            description="Agent with custom builder",
            prompt_builder=custom_builder,
        )

        result = profile.prompt_builder({"task": "Do something", "context": "Important"})
        assert "Task: Do something" in result
        assert "Context: Important" in result


class TestSubAgentRegistration:
    """Test sub-agent registration functions."""

    def test_is_sub_agent_tool(self):
        """Test is_sub_agent_tool function."""
        from klaude_code.protocol.sub_agent import is_sub_agent_tool

        # These are registered in sub_agent.py module
        assert is_sub_agent_tool("Task") is True
        assert is_sub_agent_tool("Explore") is True
        assert is_sub_agent_tool("NotAnAgent") is False

    def test_get_sub_agent_profile(self):
        """Test get_sub_agent_profile function."""
        from klaude_code.protocol.sub_agent import get_sub_agent_profile

        profile = get_sub_agent_profile("Task")
        assert profile.name == "Task"
        assert "Task" in profile.active_form or profile.active_form == "Tasking"

    def test_get_sub_agent_profile_not_found(self):
        """Test get_sub_agent_profile raises for unknown type."""
        from klaude_code.protocol.sub_agent import get_sub_agent_profile

        with pytest.raises(KeyError) as exc_info:
            get_sub_agent_profile("NonExistent")
        assert "Unknown sub agent type" in str(exc_info.value)

    def test_iter_sub_agent_profiles(self):
        """Test iter_sub_agent_profiles function."""
        from klaude_code.protocol.sub_agent import iter_sub_agent_profiles

        profiles = iter_sub_agent_profiles()
        assert len(profiles) > 0
        names = [p.name for p in profiles]
        assert "Task" in names

    def test_iter_sub_agent_profiles_enabled_only(self):
        """Test iter_sub_agent_profiles with enabled_only filter."""
        from klaude_code.protocol.sub_agent import iter_sub_agent_profiles

        # All default profiles should be enabled
        enabled = iter_sub_agent_profiles(enabled_only=True)
        assert len(enabled) > 0

    def test_sub_agent_tool_names(self):
        """Test sub_agent_tool_names function."""
        from klaude_code.protocol.sub_agent import sub_agent_tool_names

        names = sub_agent_tool_names()
        assert "Task" in names
        assert "Explore" in names
