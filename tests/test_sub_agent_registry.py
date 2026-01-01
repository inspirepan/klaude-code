from __future__ import annotations

import asyncio

import pytest

import klaude_code.core.tool as core_tool
from klaude_code.core.tool import ToolABC, load_agent_tools
from klaude_code.core.tool.tool_abc import ToolConcurrencyPolicy, ToolMetadata
from klaude_code.core.tool.tool_runner import ToolCallRequest, ToolExecutor
from klaude_code.protocol import llm_param, model
from klaude_code.protocol.sub_agent import sub_agent_tool_names


def test_sub_agent_tool_visibility_respects_filters() -> None:
    gpt5_tools = set(sub_agent_tool_names(enabled_only=True, model_name="gpt-5"))
    claude_tools = set(sub_agent_tool_names(enabled_only=True, model_name="claude-3"))

    assert gpt5_tools == claude_tools
    assert {"Task", "Explore", "WebAgent"}.issubset(gpt5_tools)


def test_main_agent_tools_include_registered_sub_agents() -> None:
    assert core_tool is not None  # ensure tool registry side-effects executed
    gpt5_tool_names = {schema.name for schema in load_agent_tools("gpt-5")}
    claude_tool_names = {schema.name for schema in load_agent_tools("claude-3")}

    assert "Task" in gpt5_tool_names
    assert "Explore" in gpt5_tool_names
    assert "WebAgent" in gpt5_tool_names
    assert "Oracle" not in gpt5_tool_names

    assert {"Task", "Explore", "WebAgent"}.issubset(claude_tool_names)
    assert "Oracle" not in claude_tool_names


class _SlowSubAgentTool(ToolABC):
    """Test-only slow tool used to exercise sub-agent cancellation behavior."""

    started: asyncio.Event | None = None

    @classmethod
    def metadata(cls) -> ToolMetadata:
        return ToolMetadata(concurrency_policy=ToolConcurrencyPolicy.CONCURRENT, has_side_effects=True)

    @classmethod
    def schema(cls) -> llm_param.ToolSchema:
        # Schema is not used in this test; return a minimal valid schema.
        return llm_param.ToolSchema(
            name="Explore",
            type="function",
            description="Slow sub-agent tool for cancellation tests",
            parameters={"type": "object", "properties": {}},
        )

    @classmethod
    async def call(cls, arguments: str) -> model.ToolResultMessage:
        assert cls.started is not None
        cls.started.set()
        try:
            # Block until the surrounding task is cancelled.
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            # Re-raise so outer layers can observe cooperative cancellation.
            raise

        return model.ToolResultMessage(
            output_text="should not complete",
            status="success",
        )


def _consume_tool_executor(executor: ToolExecutor, tool_calls: list[ToolCallRequest]) -> asyncio.Task[None]:
    async def _runner() -> None:
        async for _ in executor.run_tools(tool_calls):
            pass

    return asyncio.create_task(_runner())


def test_sub_agent_tool_cancellation_propagates_cancelled_error() -> None:
    async def _test() -> None:
        started_event = asyncio.Event()
        _SlowSubAgentTool.started = started_event

        executor = ToolExecutor(
            registry={"Explore": _SlowSubAgentTool},
            append_history=lambda items: None,  # type: ignore[arg-type]
        )

        tool_call = ToolCallRequest(
            response_id="resp1",
            call_id="tc1",
            tool_name="Explore",
            arguments_json="{}",
        )

        task = _consume_tool_executor(executor, [tool_call])

        # Wait until the fake sub-agent tool call has started so we know the
        # executor is blocked inside run_tools on the sub-agent task.
        await asyncio.wait_for(started_event.wait(), timeout=1.0)
        assert executor._concurrent_tasks  # pyright: ignore[reportPrivateUsage]

        # Cancelling the outer task should propagate asyncio.CancelledError all
        # the way out instead of being swallowed inside ToolExecutor.
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(_test())
