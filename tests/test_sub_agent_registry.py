from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, cast

import pytest

import klaude_code.core.tool as core_tool
from klaude_code.core.agent_profile import load_agent_tools
from klaude_code.core.tool import ToolABC
from klaude_code.core.tool.agent_tool import AgentTool
from klaude_code.core.tool.context import TodoContext, ToolContext
from klaude_code.core.tool.tool_abc import ToolConcurrencyPolicy, ToolMetadata
from klaude_code.core.tool.tool_runner import ToolCallRequest, ToolExecutionResult, ToolExecutor
from klaude_code.llm.openai_responses.client import ResponsesClient
from klaude_code.protocol import llm_param, message, model, tools
from klaude_code.protocol.sub_agent import SubAgentResult, is_sub_agent_tool


def _tool_context() -> ToolContext:
    todo_context = TodoContext(get_todos=lambda: [], set_todos=lambda todos: None)
    return ToolContext(file_tracker={}, todo_context=todo_context, session_id="test", work_dir=Path("/tmp"))


def test_sub_agent_tool_visibility() -> None:
    assert is_sub_agent_tool(tools.AGENT) is True
    assert is_sub_agent_tool("Finder") is False


def test_main_agent_tools_include_registered_sub_agents() -> None:
    assert core_tool is not None  # ensure tool registry side-effects executed
    gpt5_tool_names = {schema.name for schema in load_agent_tools("gpt-5")}
    claude_tool_names = {schema.name for schema in load_agent_tools("claude-3")}

    assert tools.AGENT in gpt5_tool_names
    assert "Finder" not in gpt5_tool_names
    assert "Oracle" not in gpt5_tool_names

    assert tools.AGENT in claude_tool_names
    assert "Finder" not in claude_tool_names
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
            name=tools.AGENT,
            type="function",
            description="Slow sub-agent tool for cancellation tests",
            parameters={"type": "object", "properties": {}},
        )

    @classmethod
    async def call(cls, arguments: str, context: ToolContext) -> message.ToolResultMessage:
        del arguments
        del context
        assert cls.started is not None
        cls.started.set()
        try:
            # Block until the surrounding task is cancelled.
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            # Re-raise so outer layers can observe cooperative cancellation.
            raise

        return message.ToolResultMessage(
            output_text="should not complete",
            status="success",
        )


class _BlockingCompletedConnection:
    def __init__(self, response_id: str, text: str, started: asyncio.Event, release: asyncio.Event) -> None:
        self.sent: list[str] = []
        self.close_calls = 0
        self._started = started
        self._release = release
        self._receiving = False
        self._done = False
        self._payload: dict[str, Any] = {
            "type": "response.completed",
            "response": {
                "id": response_id,
                "created_at": 0,
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "id": f"msg_{response_id}",
                        "role": "assistant",
                        "status": "completed",
                        "content": [{"type": "output_text", "text": text, "annotations": []}],
                    }
                ],
            },
        }

    async def send(self, data: str) -> None:
        self.sent.append(data)

    async def recv(self, decode: bool = False) -> bytes:
        del decode
        if self._done:
            raise AssertionError("recv called after completed response")
        if self._receiving:
            raise AssertionError("recv called concurrently on the same websocket")
        self._receiving = True
        self._started.set()
        await self._release.wait()
        try:
            self._done = True
            return json.dumps(self._payload).encode()
        finally:
            self._receiving = False

    async def close(self) -> None:
        self.close_calls += 1


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
            context=_tool_context(),
            registry={"Finder": _SlowSubAgentTool},
            append_history=lambda items: None,  # type: ignore[arg-type]
        )

        tool_call = ToolCallRequest(
            response_id="resp1",
            call_id="tc1",
            tool_name="Finder",
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


def test_agent_tool_concurrent_sub_agents_share_responses_client_safely() -> None:
    async def _test() -> None:
        release = asyncio.Event()
        started_one = asyncio.Event()
        started_two = asyncio.Event()
        connection_one = _BlockingCompletedConnection("resp_1", "subagent one", started_one, release)
        connection_two = _BlockingCompletedConnection("resp_2", "subagent two", started_two, release)
        connections = iter([connection_one, connection_two])

        shared_client = ResponsesClient(
            llm_param.LLMConfigParameter(
                provider_name="test",
                protocol=llm_param.LLMClientProtocol.RESPONSES,
                model_id="gpt-5.4",
                api_key="test-key",
            )
        )
        ws_transport = cast(Any, shared_client)._ws_transport
        assert ws_transport is not None

        async def _open_connection() -> Any:
            return next(connections)

        ws_transport._open_connection = _open_connection

        async def _run_subtask(
            state: Any,
            record_session_id: Any,
            register_metadata_getter: Any,
            register_progress_getter: Any,
        ) -> SubAgentResult:
            del register_metadata_getter
            del register_progress_getter
            if callable(record_session_id):
                record_session_id(f"session-{state.sub_agent_desc}")

            stream = await shared_client.call(
                llm_param.LLMCallParameter(
                    input=[message.UserMessage(parts=[message.TextPart(text=state.sub_agent_prompt)])],
                    model_id="gpt-5.4",
                    session_id=f"call-{state.sub_agent_desc}",
                    tools=[],
                )
            )

            final_message: message.AssistantMessage | None = None
            async for item in stream:
                if isinstance(item, message.AssistantMessage):
                    final_message = item

            assert final_message is not None
            return SubAgentResult(
                task_result=message.join_text_parts(final_message.parts),
                session_id=f"session-{state.sub_agent_desc}",
            )

        todo_context = TodoContext(get_todos=lambda: [], set_todos=lambda todos: None)
        context = ToolContext(
            file_tracker={},
            todo_context=todo_context,
            session_id="test",
            work_dir=Path("/tmp"),
            run_subtask=_run_subtask,
        )
        history: list[message.HistoryEvent] = []
        executor = ToolExecutor(context=context, registry={tools.AGENT: AgentTool}, append_history=history.extend)

        tool_calls = [
            ToolCallRequest(
                response_id="resp-parent",
                call_id="call-1",
                tool_name=tools.AGENT,
                arguments_json='{"type":"finder","description":"one","prompt":"first"}',
            ),
            ToolCallRequest(
                response_id="resp-parent",
                call_id="call-2",
                tool_name=tools.AGENT,
                arguments_json='{"type":"general-purpose","description":"two","prompt":"second"}',
            ),
        ]

        async def _collect_events() -> list[object]:
            return [event async for event in executor.run_tools(tool_calls)]

        events_task = asyncio.create_task(_collect_events())
        await asyncio.wait_for(asyncio.gather(started_one.wait(), started_two.wait()), timeout=1)
        release.set()

        events = await events_task
        results = [event for event in events if isinstance(event, ToolExecutionResult)]
        session_ids = {
            ui_extra.session_id
            for result in results
            if isinstance((ui_extra := result.tool_result.ui_extra), model.SessionIdUIExtra)
        }

        assert len(results) == 2
        assert {result.tool_result.output_text for result in results} == {"subagent one", "subagent two"}
        assert session_ids == {"session-one", "session-two"}
        assert len(connection_one.sent) == 1
        assert len(connection_two.sent) == 1
        assert connection_one.close_calls == 1
        assert connection_two.close_calls == 1

    asyncio.run(_test())
