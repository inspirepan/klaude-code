# pyright: reportPrivateUsage=false
from __future__ import annotations

import asyncio
import os
import shutil
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from klaude_code.protocol import llm_param, message
from klaude_code.protocol.models import (
    SessionIdUIExtra,
    TaskMetadata,
    TodoItem,
    TodoListUIExtra,
    TodoUIExtra,
    ToolSideEffect,
    Usage,
)
from klaude_code.tool.core.abc import ToolABC, ToolConcurrencyPolicy, ToolMetadata
from klaude_code.tool.core.context import TodoContext, ToolContext
from klaude_code.tool.core.runner import (
    ToolCallRequest,
    ToolExecutionCallStarted,
    ToolExecutionOutputDelta,
    ToolExecutionResult,
    ToolExecutionTodoChange,
    ToolExecutor,
    ToolExecutorEvent,
    run_tool,
)
from klaude_code.tool.shell.bash_tool import BashTool


def _tool_context() -> ToolContext:
    todo_context = TodoContext(get_todos=lambda: [], set_todos=lambda todos: None)
    return ToolContext(file_tracker={}, todo_context=todo_context, session_id="test", work_dir=Path("/tmp"))


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
    async def call(cls, arguments: str, context: ToolContext) -> message.ToolResultMessage:
        del arguments
        del context
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
    async def call(cls, arguments: str, context: ToolContext) -> message.ToolResultMessage:
        del arguments
        del context
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
    async def call(cls, arguments: str, context: ToolContext) -> message.ToolResultMessage:
        del arguments
        del context
        todos = [TodoItem(content="Test todo", status="pending")]
        ui_extra = TodoListUIExtra(todo_list=TodoUIExtra(todos=todos, new_completed=[]))
        return message.ToolResultMessage(
            status="success",
            output_text="Todo updated",
            ui_extra=ui_extra,
            side_effects=[ToolSideEffect.TODO_CHANGE],
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
    async def call(cls, arguments: str, context: ToolContext) -> message.ToolResultMessage:
        del arguments
        del context
        return message.ToolResultMessage(status="success", output_text="Concurrent!")


class MockStreamingTool(ToolABC):
    """Mock tool that emits incremental output."""

    @classmethod
    def schema(cls) -> llm_param.ToolSchema:
        return llm_param.ToolSchema(
            name="MockStreaming",
            type="function",
            description="Mock streaming tool",
            parameters={"type": "object", "properties": {}},
        )

    @classmethod
    async def call(cls, arguments: str, context: ToolContext) -> message.ToolResultMessage:
        del arguments
        if context.emit_tool_output_delta is not None:
            await context.emit_tool_output_delta("alpha")
            await context.emit_tool_output_delta("beta")
        return message.ToolResultMessage(status="success", output_text="alphabeta")


class MockSlowStreamingTool(ToolABC):
    """Mock tool that emits one chunk, waits, then returns."""

    @classmethod
    def schema(cls) -> llm_param.ToolSchema:
        return llm_param.ToolSchema(
            name="MockSlowStreaming",
            type="function",
            description="Mock slow streaming tool",
            parameters={"type": "object", "properties": {}},
        )

    @classmethod
    async def call(cls, arguments: str, context: ToolContext) -> message.ToolResultMessage:
        del arguments
        if context.emit_tool_output_delta is not None:
            await context.emit_tool_output_delta("first")
        await asyncio.sleep(0.2)
        return message.ToolResultMessage(status="success", output_text="done")


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
        result = arun(run_tool(tool_call, registry, _tool_context()))

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
        result = arun(run_tool(tool_call, registry, _tool_context()))

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
        result = arun(run_tool(tool_call, registry, _tool_context()))

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
            "MockStreaming": MockStreamingTool,
            "MockSlowStreaming": MockSlowStreamingTool,
        }

    @pytest.fixture
    def history(self) -> list[message.HistoryEvent]:
        return []

    @pytest.fixture
    def executor(self, registry: dict[str, type[ToolABC]], history: list[message.HistoryEvent]) -> ToolExecutor:
        def append_history(items: Sequence[message.HistoryEvent]) -> None:
            history.extend(items)

        return ToolExecutor(context=_tool_context(), registry=registry, append_history=append_history)

    def test_run_single_tool(self, executor: ToolExecutor):
        """Test running a single tool call."""
        tool_call = ToolCallRequest(
            response_id=None,
            call_id="test_123",
            tool_name="MockSuccess",
            arguments_json="{}",
        )

        async def collect_events() -> list[ToolExecutorEvent]:
            events: list[ToolExecutorEvent] = []
            async for event in executor.run_tools([tool_call]):
                events.append(event)
            return events

        events = arun(collect_events())

        # Should have call started and result events
        assert len(events) == 2
        assert isinstance(events[0], ToolExecutionCallStarted)
        assert isinstance(events[1], ToolExecutionResult)

    def test_run_streaming_tool(self, executor: ToolExecutor) -> None:
        tool_call = ToolCallRequest(
            response_id=None,
            call_id="stream_123",
            tool_name="MockStreaming",
            arguments_json="{}",
        )

        async def collect_events() -> list[ToolExecutorEvent]:
            events: list[ToolExecutorEvent] = []
            async for event in executor.run_tools([tool_call]):
                events.append(event)
            return events

        events = arun(collect_events())

        assert isinstance(events[0], ToolExecutionCallStarted)
        assert isinstance(events[1], ToolExecutionOutputDelta)
        assert events[1].content == "alpha"
        assert isinstance(events[2], ToolExecutionOutputDelta)
        assert events[2].content == "beta"
        assert isinstance(events[3], ToolExecutionResult)
        assert events[3].tool_result.output_text == "alphabeta"

    def test_run_streaming_tool_emits_delta_before_completion(self, executor: ToolExecutor) -> None:
        tool_call = ToolCallRequest(
            response_id=None,
            call_id="slow_stream_123",
            tool_name="MockSlowStreaming",
            arguments_json="{}",
        )

        async def collect_first_event_before_completion() -> tuple[ToolExecutionOutputDelta, list[ToolExecutorEvent]]:
            seen: list[ToolExecutorEvent] = []
            stream = executor.run_tools([tool_call])

            first = await anext(stream)
            seen.append(first)
            second = await asyncio.wait_for(anext(stream), timeout=0.1)
            seen.append(second)

            rest: list[ToolExecutorEvent] = []
            async for event in stream:
                rest.append(event)
            assert isinstance(second, ToolExecutionOutputDelta)
            return second, [*seen, *rest]

        first_delta, events = arun(collect_first_event_before_completion())

        assert isinstance(first_delta, ToolExecutionOutputDelta)
        assert first_delta.content == "first"
        assert isinstance(events[-1], ToolExecutionResult)

    def test_run_multiple_tools_sequentially(self, executor: ToolExecutor):
        """Test running multiple regular tools sequentially."""
        tool_calls = [
            ToolCallRequest(response_id=None, call_id="test_1", tool_name="MockSuccess", arguments_json="{}"),
            ToolCallRequest(response_id=None, call_id="test_2", tool_name="MockSuccess", arguments_json="{}"),
        ]

        async def collect_events() -> list[ToolExecutorEvent]:
            events: list[ToolExecutorEvent] = []
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

        async def collect_events() -> list[ToolExecutorEvent]:
            events: list[ToolExecutorEvent] = []
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

        events = list(executor.on_interrupt())

        # Should have call started and result (aborted) events
        assert len(events) == 2
        assert isinstance(events[0], ToolExecutionCallStarted)
        assert isinstance(events[1], ToolExecutionResult)
        assert events[1].tool_result.status == "aborted"

    def test_cancel_includes_session_id_ui_extra_when_available(self, executor: ToolExecutor):
        tool_call = ToolCallRequest(
            response_id=None,
            call_id="test_123",
            tool_name="MockSuccess",
            arguments_json="{}",
        )
        executor._unfinished_calls["test_123"] = tool_call
        executor._sub_agent_session_ids["test_123"] = "session_abc"  # pyright: ignore[reportPrivateUsage]

        events = list(executor.on_interrupt())

        assert len(events) == 2
        assert isinstance(events[1], ToolExecutionResult)
        assert isinstance(events[1].tool_result.ui_extra, SessionIdUIExtra)
        assert events[1].tool_result.ui_extra.session_id == "session_abc"

    def test_cancel_includes_task_metadata_when_available(self, executor: ToolExecutor):
        """Test cancelling includes sub-agent task metadata when getter is registered."""
        tool_call = ToolCallRequest(
            response_id=None,
            call_id="test_123",
            tool_name="MockSuccess",
            arguments_json="{}",
        )
        executor._unfinished_calls["test_123"] = tool_call
        executor._sub_agent_metadata_getters["test_123"] = lambda: TaskMetadata(
            model_name="test-model",
            usage=Usage(input_tokens=100, output_tokens=50),
            description="Test sub-agent",
        )

        events = list(executor.on_interrupt())

        assert len(events) == 2
        assert isinstance(events[1], ToolExecutionResult)
        assert events[1].tool_result.task_metadata is not None
        assert events[1].tool_result.task_metadata.model_name == "test-model"
        assert events[1].tool_result.task_metadata.description == "Test sub-agent"
        assert events[1].tool_result.task_metadata.usage is not None
        assert events[1].tool_result.task_metadata.usage.input_tokens == 100

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

        events = list(executor.on_interrupt())

        # Should only have result event (call started was already emitted)
        assert len(events) == 1
        assert isinstance(events[0], ToolExecutionResult)

    def test_cancel_with_no_unfinished(self, executor: ToolExecutor):
        """Test cancel with no unfinished calls."""
        events = list(executor.on_interrupt())
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
            context=_tool_context(),
            registry={"Read": MockSuccessTool, "Bash": MockSuccessTool},
            append_history=lambda items: None,  # type: ignore[arg-type]
        )
        sequential, concurrent = executor._partition_tool_calls(tool_calls)

        assert len(sequential) == 2
        assert len(concurrent) == 0

    def test_partition_concurrent_tools_only(self):
        """Test partitioning with only concurrent tools."""
        tool_calls = [
            ToolCallRequest(response_id=None, call_id="1", tool_name="Agent", arguments_json="{}"),
            ToolCallRequest(response_id=None, call_id="2", tool_name="Finder", arguments_json="{}"),
        ]
        executor = ToolExecutor(
            context=_tool_context(),
            registry={"Agent": MockConcurrentTool, "Finder": MockConcurrentTool},
            append_history=lambda items: None,  # type: ignore[arg-type]
        )
        sequential, concurrent = executor._partition_tool_calls(tool_calls)

        assert len(sequential) == 0
        assert len(concurrent) == 2

    def test_partition_mixed_tools(self):
        """Test partitioning with mixed tool types."""
        tool_calls = [
            ToolCallRequest(response_id=None, call_id="1", tool_name="Read", arguments_json="{}"),
            ToolCallRequest(response_id=None, call_id="2", tool_name="Agent", arguments_json="{}"),
            ToolCallRequest(response_id=None, call_id="3", tool_name="Bash", arguments_json="{}"),
        ]
        executor = ToolExecutor(
            context=_tool_context(),
            registry={"Read": MockSuccessTool, "Bash": MockSuccessTool, "Agent": MockConcurrentTool},
            append_history=lambda items: None,  # type: ignore[arg-type]
        )
        sequential, concurrent = executor._partition_tool_calls(tool_calls)

        assert len(sequential) == 2
        assert len(concurrent) == 1
        assert sequential[0].tool_name == "Read"
        assert sequential[1].tool_name == "Bash"
        assert concurrent[0].tool_name == "Agent"

    def test_partition_web_tools_as_concurrent(self):
        """Test that web tools are partitioned as concurrent."""
        tool_calls = [
            ToolCallRequest(response_id=None, call_id="1", tool_name="Read", arguments_json="{}"),
            ToolCallRequest(response_id=None, call_id="2", tool_name="WebSearch", arguments_json="{}"),
            ToolCallRequest(response_id=None, call_id="3", tool_name="WebFetch", arguments_json="{}"),
            ToolCallRequest(response_id=None, call_id="4", tool_name="Agent", arguments_json="{}"),
        ]
        executor = ToolExecutor(
            context=_tool_context(),
            registry={
                "Read": MockSuccessTool,
                "WebSearch": MockConcurrentTool,
                "WebFetch": MockConcurrentTool,
                "Agent": MockConcurrentTool,
            },
            append_history=lambda items: None,  # type: ignore[arg-type]
        )
        sequential, concurrent = executor._partition_tool_calls(tool_calls)

        assert len(sequential) == 1
        assert len(concurrent) == 3
        assert sequential[0].tool_name == "Read"
        assert {c.tool_name for c in concurrent} == {"WebSearch", "WebFetch", "Agent"}


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
            TodoItem(content="Task 1", status="pending"),
            TodoItem(content="Task 2", status="completed"),
        ]
        event = ToolExecutionTodoChange(todos=todos)
        assert len(event.todos) == 2
        assert event.todos[0].content == "Task 1"


class TestBuildToolSideEffectEvents:
    """Test ToolExecutor._build_tool_side_effect_events method."""

    @pytest.fixture
    def executor(self) -> ToolExecutor:
        return ToolExecutor(
            context=_tool_context(),
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
        todos = [TodoItem(content="Task", status="pending")]
        ui_extra = TodoListUIExtra(todo_list=TodoUIExtra(todos=todos, new_completed=[]))
        result = message.ToolResultMessage(
            status="success",
            output_text="Done",
            ui_extra=ui_extra,
            side_effects=[ToolSideEffect.TODO_CHANGE],
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
            side_effects=[ToolSideEffect.TODO_CHANGE],
        )
        events = executor._build_tool_side_effect_events(result)
        assert events == []


class TestBashToolCancellation:
    def test_bash_tool_propagates_cancelled_error(self) -> None:
        if os.name != "posix" or shutil.which("bash") is None:
            pytest.skip("bash tool requires POSIX + bash")

        async def _run() -> None:
            args = BashTool.BashArguments(command="sleep 10", timeout_ms=60_000)
            task = asyncio.create_task(BashTool.call_with_args(args, _tool_context()))
            await asyncio.sleep(0.1)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

        arun(_run())


class TestBashToolStreaming:
    def test_bash_tool_sets_python_unbuffered(self) -> None:
        if os.name != "posix" or shutil.which("bash") is None:
            pytest.skip("bash tool requires POSIX + bash")

        async def _run() -> None:
            args = BashTool.BashArguments(
                command="python -c 'import os; print(os.getenv(\"PYTHONUNBUFFERED\"))'", timeout_ms=5_000
            )
            result = await BashTool.call_with_args(args, _tool_context())
            assert result.output_text == "1"

        arun(_run())

    def test_bash_command_emits_output_delta_immediately(self) -> None:
        if os.name != "posix" or shutil.which("bash") is None:
            pytest.skip("bash tool requires POSIX + bash")

        emitted: list[str] = []

        async def _emit(content: str) -> None:
            emitted.append(content)

        async def _run() -> None:
            args = BashTool.BashArguments(command="echo short; sleep 0.1; echo done", timeout_ms=5_000)
            result = await BashTool.call_with_args(args, _tool_context().with_emit_tool_output_delta(_emit))
            assert result.output_text == "short\ndone"

        arun(_run())

        assert emitted
        assert "".join(emitted) == "short\ndone\n"

    def test_bash_timeout_preserves_partial_output(self) -> None:
        if os.name != "posix" or shutil.which("bash") is None:
            pytest.skip("bash tool requires POSIX + bash")

        async def _run() -> None:
            # Print something, then sleep longer than the timeout.
            args = BashTool.BashArguments(
                command="echo partial_before_timeout; sleep 30",
                timeout_ms=500,
            )
            result = await BashTool.call_with_args(args, _tool_context())
            assert result.status == "error"
            assert "Timeout after 500 ms" in result.output_text
            assert "partial_before_timeout" in result.output_text

        arun(_run())
