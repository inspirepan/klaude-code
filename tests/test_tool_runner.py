# pyright: reportPrivateUsage=false
"""Tests for tool_runner module."""

from __future__ import annotations

import asyncio
import os
import shutil
from collections.abc import Sequence
from typing import Any

import pytest

from klaude_code.core.tool.shell.bash_tool import BashTool
from klaude_code.core.tool.tool_abc import ToolABC, ToolConcurrencyPolicy, ToolMetadata
from klaude_code.core.tool.tool_runner import (
    ToolCallRequest,
    ToolExecutionCallStarted,
    ToolExecutionResult,
    ToolExecutionTodoChange,
    ToolExecutor,
    run_tool,
)
from klaude_code.protocol import llm_param, message, model


def arun(coro: Any) -> Any:
    """Helper to run async coroutines."""
    return asyncio.run(coro)


class MockSuccessTool(ToolABC):
    """Mock tool that succeeds."""

    @classmethod
    def schema(cls) -> llm_param.ToolSchema:
        return llm_param.ToolSchema(
            name="MockSuccess",
            type="function",
            description="Mock success tool",
            parameters={"type": "object", "properties": {}},
        )

    @classmethod
    async def call(cls, arguments: str) -> message.ToolResultMessage:
        return message.ToolResultMessage(status="success", output_text="Success!")


class MockErrorTool(ToolABC):
    """Mock tool that raises an exception."""

    @classmethod
    def schema(cls) -> llm_param.ToolSchema:
        return llm_param.ToolSchema(
            name="MockError",
            type="function",
            description="Mock error tool",
            parameters={"type": "object", "properties": {}},
        )

    @classmethod
    async def call(cls, arguments: str) -> message.ToolResultMessage:
        raise ValueError("Something went wrong")


class MockTodoChangeTool(ToolABC):
    """Mock tool that triggers todo change side effect."""

    @classmethod
    def schema(cls) -> llm_param.ToolSchema:
        return llm_param.ToolSchema(
            name="MockTodoChange",
            type="function",
            description="Mock todo change tool",
            parameters={"type": "object", "properties": {}},
        )

    @classmethod
    async def call(cls, arguments: str) -> message.ToolResultMessage:
        todos = [model.TodoItem(content="Test todo", status="pending")]
        ui_extra = model.TodoListUIExtra(todo_list=model.TodoUIExtra(todos=todos, new_completed=[]))
        return message.ToolResultMessage(
            status="success",
            output_text="Todo updated",
            ui_extra=ui_extra,
            side_effects=[model.ToolSideEffect.TODO_CHANGE],
        )


class MockConcurrentTool(ToolABC):
    """Mock tool marked as concurrent."""

    @classmethod
    def metadata(cls) -> ToolMetadata:
        return ToolMetadata(concurrency_policy=ToolConcurrencyPolicy.CONCURRENT, has_side_effects=False)

    @classmethod
    def schema(cls) -> llm_param.ToolSchema:
        return llm_param.ToolSchema(
            name="MockConcurrent",
            type="function",
            description="Mock concurrent tool",
            parameters={"type": "object", "properties": {}},
        )

    @classmethod
    async def call(cls, arguments: str) -> message.ToolResultMessage:
        return message.ToolResultMessage(status="success", output_text="Concurrent!")


class TestRunTool:
    """Test run_tool function."""

    @pytest.fixture
    def registry(self) -> dict[str, type[ToolABC]]:
        return {
            "MockSuccess": MockSuccessTool,
            "MockError": MockErrorTool,
            "MockTodoChange": MockTodoChangeTool,
        }

    def test_successful_tool_call(self, registry: dict[str, type[ToolABC]]):
        """Test successful tool execution."""
        tool_call = ToolCallRequest(
            response_id=None,
            call_id="test_123",
            tool_name="MockSuccess",
            arguments_json="{}",
        )
        result = arun(run_tool(tool_call, registry))

        assert result.status == "success"
        assert result.output_text == "Success!"
        assert result.call_id == "test_123"
        assert result.tool_name == "MockSuccess"

    def test_tool_not_found(self, registry: dict[str, type[ToolABC]]):
        """Test calling non-existent tool."""
        tool_call = ToolCallRequest(
            response_id=None,
            call_id="test_123",
            tool_name="NonExistent",
            arguments_json="{}",
        )
        result = arun(run_tool(tool_call, registry))

        assert result.status == "error"
        assert result.output_text is not None and "not exists" in result.output_text
        assert result.tool_name == "NonExistent"

    def test_tool_exception_handling(self, registry: dict[str, type[ToolABC]]):
        """Test tool that raises exception."""
        tool_call = ToolCallRequest(
            response_id=None,
            call_id="test_123",
            tool_name="MockError",
            arguments_json="{}",
        )
        result = arun(run_tool(tool_call, registry))

        assert result.status == "error"
        assert result.output_text is not None and "ValueError" in result.output_text
        assert "Something went wrong" in result.output_text


class TestToolExecutor:
    """Test ToolExecutor class."""

    @pytest.fixture
    def registry(self) -> dict[str, type[ToolABC]]:
        return {
            "MockSuccess": MockSuccessTool,
            "MockTodoChange": MockTodoChangeTool,
        }

    @pytest.fixture
    def history(self) -> list[message.HistoryEvent]:
        return []

    @pytest.fixture
    def executor(self, registry: dict[str, type[ToolABC]], history: list[message.HistoryEvent]) -> ToolExecutor:
        def append_history(items: Sequence[message.HistoryEvent]) -> None:
            history.extend(items)

        return ToolExecutor(registry=registry, append_history=append_history)

    def test_run_single_tool(self, executor: ToolExecutor):
        """Test running a single tool call."""
        tool_call = ToolCallRequest(
            response_id=None,
            call_id="test_123",
            tool_name="MockSuccess",
            arguments_json="{}",
        )

        async def collect_events() -> list[ToolExecutionCallStarted | ToolExecutionResult | ToolExecutionTodoChange]:
            events: list[ToolExecutionCallStarted | ToolExecutionResult | ToolExecutionTodoChange] = []
            async for event in executor.run_tools([tool_call]):
                events.append(event)
            return events

        events = arun(collect_events())

        # Should have call started and result events
        assert len(events) == 2
        assert isinstance(events[0], ToolExecutionCallStarted)
        assert isinstance(events[1], ToolExecutionResult)
        assert events[0].tool_call.call_id == "test_123"
        assert events[1].tool_result.status == "success"

    def test_run_multiple_tools_sequentially(self, executor: ToolExecutor):
        """Test running multiple regular tools sequentially."""
        tool_calls = [
            ToolCallRequest(response_id=None, call_id="test_1", tool_name="MockSuccess", arguments_json="{}"),
            ToolCallRequest(response_id=None, call_id="test_2", tool_name="MockSuccess", arguments_json="{}"),
        ]

        async def collect_events() -> list[ToolExecutionCallStarted | ToolExecutionResult | ToolExecutionTodoChange]:
            events: list[ToolExecutionCallStarted | ToolExecutionResult | ToolExecutionTodoChange] = []
            async for event in executor.run_tools(tool_calls):
                events.append(event)
            return events

        events = arun(collect_events())

        # Each tool should have call started + result
        assert len(events) == 4
        call_started_events = [e for e in events if isinstance(e, ToolExecutionCallStarted)]
        result_events = [e for e in events if isinstance(e, ToolExecutionResult)]
        assert len(call_started_events) == 2
        assert len(result_events) == 2

    def test_todo_change_side_effect(self, executor: ToolExecutor):
        """Test tool emitting todo change side effect."""
        tool_call = ToolCallRequest(
            response_id=None,
            call_id="test_123",
            tool_name="MockTodoChange",
            arguments_json="{}",
        )

        async def collect_events() -> list[ToolExecutionCallStarted | ToolExecutionResult | ToolExecutionTodoChange]:
            events: list[ToolExecutionCallStarted | ToolExecutionResult | ToolExecutionTodoChange] = []
            async for event in executor.run_tools([tool_call]):
                events.append(event)
            return events

        events = arun(collect_events())

        # Should have call started, result, and todo change events
        todo_events = [e for e in events if isinstance(e, ToolExecutionTodoChange)]
        assert len(todo_events) == 1
        assert len(todo_events[0].todos) == 1
        assert todo_events[0].todos[0].content == "Test todo"

    def test_cancel_unfinished_tools(self, executor: ToolExecutor):
        """Test cancelling unfinished tool calls."""
        # Manually add unfinished calls
        tool_call = ToolCallRequest(
            response_id=None,
            call_id="test_123",
            tool_name="MockSuccess",
            arguments_json="{}",
        )
        executor._unfinished_calls["test_123"] = tool_call

        events = list(executor.cancel())

        # Should have call started and result (aborted) events
        assert len(events) == 2
        assert isinstance(events[0], ToolExecutionCallStarted)
        assert isinstance(events[1], ToolExecutionResult)
        assert events[1].tool_result.status == "aborted"

    def test_cancel_already_emitted_call(self, executor: ToolExecutor):
        """Test cancelling call that was already emitted."""
        tool_call = ToolCallRequest(
            response_id=None,
            call_id="test_123",
            tool_name="MockSuccess",
            arguments_json="{}",
        )
        executor._unfinished_calls["test_123"] = tool_call
        executor._call_event_emitted.add("test_123")

        events = list(executor.cancel())

        # Should only have result event (call started was already emitted)
        assert len(events) == 1
        assert isinstance(events[0], ToolExecutionResult)

    def test_cancel_with_no_unfinished(self, executor: ToolExecutor):
        """Test cancel with no unfinished calls."""
        events = list(executor.cancel())
        assert events == []


class TestToolExecutorPartition:
    """Test ToolExecutor._partition_tool_calls static method."""

    def test_partition_sequential_tools_only(self):
        """Test partitioning with only sequential tools."""
        tool_calls = [
            ToolCallRequest(response_id=None, call_id="1", tool_name="Read", arguments_json="{}"),
            ToolCallRequest(response_id=None, call_id="2", tool_name="Bash", arguments_json="{}"),
        ]
        executor = ToolExecutor(
            registry={"Read": MockSuccessTool, "Bash": MockSuccessTool},
            append_history=lambda items: None,  # type: ignore[arg-type]
        )
        sequential, concurrent = executor._partition_tool_calls(tool_calls)

        assert len(sequential) == 2
        assert len(concurrent) == 0

    def test_partition_concurrent_tools_only(self):
        """Test partitioning with only concurrent tools."""
        tool_calls = [
            ToolCallRequest(response_id=None, call_id="1", tool_name="Task", arguments_json="{}"),
            ToolCallRequest(response_id=None, call_id="2", tool_name="Explore", arguments_json="{}"),
        ]
        executor = ToolExecutor(
            registry={"Task": MockConcurrentTool, "Explore": MockConcurrentTool},
            append_history=lambda items: None,  # type: ignore[arg-type]
        )
        sequential, concurrent = executor._partition_tool_calls(tool_calls)

        assert len(sequential) == 0
        assert len(concurrent) == 2

    def test_partition_mixed_tools(self):
        """Test partitioning with mixed tool types."""
        tool_calls = [
            ToolCallRequest(response_id=None, call_id="1", tool_name="Read", arguments_json="{}"),
            ToolCallRequest(response_id=None, call_id="2", tool_name="Task", arguments_json="{}"),
            ToolCallRequest(response_id=None, call_id="3", tool_name="Bash", arguments_json="{}"),
        ]
        executor = ToolExecutor(
            registry={"Read": MockSuccessTool, "Bash": MockSuccessTool, "Task": MockConcurrentTool},
            append_history=lambda items: None,  # type: ignore[arg-type]
        )
        sequential, concurrent = executor._partition_tool_calls(tool_calls)

        assert len(sequential) == 2
        assert len(concurrent) == 1
        assert sequential[0].tool_name == "Read"
        assert sequential[1].tool_name == "Bash"
        assert concurrent[0].tool_name == "Task"

    def test_partition_web_tools_as_concurrent(self):
        """Test that web tools are partitioned as concurrent."""
        tool_calls = [
            ToolCallRequest(response_id=None, call_id="1", tool_name="Read", arguments_json="{}"),
            ToolCallRequest(response_id=None, call_id="2", tool_name="WebSearch", arguments_json="{}"),
            ToolCallRequest(response_id=None, call_id="3", tool_name="WebFetch", arguments_json="{}"),
            ToolCallRequest(response_id=None, call_id="4", tool_name="Task", arguments_json="{}"),
        ]
        executor = ToolExecutor(
            registry={
                "Read": MockSuccessTool,
                "WebSearch": MockConcurrentTool,
                "WebFetch": MockConcurrentTool,
                "Task": MockConcurrentTool,
            },
            append_history=lambda items: None,  # type: ignore[arg-type]
        )
        sequential, concurrent = executor._partition_tool_calls(tool_calls)

        assert len(sequential) == 1
        assert len(concurrent) == 3
        assert sequential[0].tool_name == "Read"
        assert {c.tool_name for c in concurrent} == {"WebSearch", "WebFetch", "Task"}


class TestToolExecutorEvents:
    """Test ToolExecutor event dataclasses."""

    def test_tool_execution_call_started(self):
        """Test ToolExecutionCallStarted dataclass."""
        tool_call = ToolCallRequest(response_id=None, call_id="123", tool_name="Test", arguments_json="{}")
        event = ToolExecutionCallStarted(tool_call=tool_call)
        assert event.tool_call.call_id == "123"
        assert event.tool_call.tool_name == "Test"

    def test_tool_execution_result(self):
        """Test ToolExecutionResult dataclass."""
        tool_call = ToolCallRequest(response_id=None, call_id="123", tool_name="Test", arguments_json="{}")
        tool_result = message.ToolResultMessage(status="success", output_text="Done")
        event = ToolExecutionResult(tool_call=tool_call, tool_result=tool_result)
        assert event.tool_call.call_id == "123"
        assert event.tool_result.status == "success"

    def test_tool_execution_todo_change(self):
        """Test ToolExecutionTodoChange dataclass."""
        todos = [
            model.TodoItem(content="Task 1", status="pending"),
            model.TodoItem(content="Task 2", status="completed"),
        ]
        event = ToolExecutionTodoChange(todos=todos)
        assert len(event.todos) == 2
        assert event.todos[0].content == "Task 1"


class TestBuildToolSideEffectEvents:
    """Test ToolExecutor._build_tool_side_effect_events method."""

    @pytest.fixture
    def executor(self) -> ToolExecutor:
        return ToolExecutor(
            registry={},
            append_history=lambda x: None,
        )

    def test_no_side_effects(self, executor: ToolExecutor):
        """Test result with no side effects."""
        result = message.ToolResultMessage(status="success", output_text="Done")
        events = executor._build_tool_side_effect_events(result)
        assert events == []

    def test_todo_change_side_effect(self, executor: ToolExecutor):
        """Test todo change side effect generates event."""
        todos = [model.TodoItem(content="Task", status="pending")]
        ui_extra = model.TodoListUIExtra(todo_list=model.TodoUIExtra(todos=todos, new_completed=[]))
        result = message.ToolResultMessage(
            status="success",
            output_text="Done",
            ui_extra=ui_extra,
            side_effects=[model.ToolSideEffect.TODO_CHANGE],
        )
        events = executor._build_tool_side_effect_events(result)

        assert len(events) == 1
        assert isinstance(events[0], ToolExecutionTodoChange)
        assert events[0].todos[0].content == "Task"

    def test_todo_change_without_ui_extra(self, executor: ToolExecutor):
        """Test todo change side effect without proper ui_extra is ignored."""
        result = message.ToolResultMessage(
            status="success",
            output_text="Done",
            side_effects=[model.ToolSideEffect.TODO_CHANGE],
        )
        events = executor._build_tool_side_effect_events(result)
        assert events == []


class TestBashToolCancellation:
    def test_bash_tool_propagates_cancelled_error(self) -> None:
        if os.name != "posix" or shutil.which("bash") is None:
            pytest.skip("bash tool requires POSIX + bash")

        async def _run() -> None:
            args = BashTool.BashArguments(command="sleep 10", timeout_ms=60_000)
            task = asyncio.create_task(BashTool.call_with_args(args))
            await asyncio.sleep(0.1)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

        arun(_run())
