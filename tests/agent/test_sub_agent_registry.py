from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

import klaude_code.agent.runtime.sub_agent as sub_agent_runtime
import klaude_code.tool as core_tool
from klaude_code.agent.agent import Agent
from klaude_code.agent.agent_profile import AgentProfile, load_agent_tools
from klaude_code.agent.runtime.llm import LLMClients
from klaude_code.agent.runtime.sub_agent import SubAgentExecutor
from klaude_code.config.config import Config, ModelConfig, ProviderConfig
from klaude_code.llm.client import LLMClientABC, LLMStreamABC
from klaude_code.protocol import events, llm_param, message, tools
from klaude_code.protocol.models import SessionIdUIExtra, SubAgentState
from klaude_code.protocol.sub_agent import SubAgentResult, is_sub_agent_tool
from klaude_code.session.session import Session
from klaude_code.tool import ToolABC, WriteTool
from klaude_code.tool.agent_tool import AgentTool
from klaude_code.tool.core.abc import ToolConcurrencyPolicy, ToolMetadata
from klaude_code.tool.core.context import TodoContext, ToolContext
from klaude_code.tool.core.registry import get_tool_schemas
from klaude_code.tool.core.runner import ToolCallRequest, ToolExecutionResult, ToolExecutor


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


def test_gpt_sub_agent_replaces_edit_and_write_with_apply_patch() -> None:
    gpt_tool_names = [schema.name for schema in load_agent_tools("gpt-4.1", "general-purpose")]
    claude_tool_names = [schema.name for schema in load_agent_tools("claude-3", "general-purpose")]

    assert tools.APPLY_PATCH in gpt_tool_names
    assert tools.EDIT not in gpt_tool_names
    assert tools.WRITE not in gpt_tool_names
    assert tools.APPLY_PATCH not in claude_tool_names
    assert tools.EDIT in claude_tool_names
    assert tools.WRITE in claude_tool_names


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


class _BlockingFakeStream(LLMStreamABC):
    """Fake LLM stream that blocks until released, then yields a single AssistantMessage."""

    def __init__(self, response_id: str, text: str, started: asyncio.Event, release: asyncio.Event) -> None:
        self._response_id = response_id
        self._text = text
        self._started = started
        self._release = release

    def __aiter__(self) -> AsyncGenerator[message.LLMStreamItem]:
        return self._iterate()

    async def _iterate(self) -> AsyncGenerator[message.LLMStreamItem]:
        self._started.set()
        await self._release.wait()
        yield message.AssistantMessage(
            parts=[message.TextPart(text=self._text)],
            response_id=self._response_id,
            stop_reason="stop",
        )

    def get_partial_message(self) -> message.AssistantMessage | None:
        return None


class _SingleMessageStream(LLMStreamABC):
    def __init__(self, text: str) -> None:
        self._text = text

    def __aiter__(self) -> AsyncGenerator[message.LLMStreamItem]:
        return self._iterate()

    async def _iterate(self) -> AsyncGenerator[message.LLMStreamItem]:
        yield message.AssistantMessage(
            parts=[message.TextPart(text=self._text)], response_id="resp", stop_reason="stop"
        )

    def get_partial_message(self) -> message.AssistantMessage | None:
        return None


class _ItemsStream(LLMStreamABC):
    def __init__(self, items: list[message.LLMStreamItem]) -> None:
        self._items = items

    def __aiter__(self) -> AsyncGenerator[message.LLMStreamItem]:
        return self._iterate()

    async def _iterate(self) -> AsyncGenerator[message.LLMStreamItem]:
        for item in self._items:
            yield item

    def get_partial_message(self) -> message.AssistantMessage | None:
        return None


class _RecordingClient(LLMClientABC):
    def __init__(self, model_id: str, response_text: str) -> None:
        super().__init__(
            llm_param.LLMConfigParameter(
                provider_name="test-provider",
                protocol=llm_param.LLMClientProtocol.OPENAI,
                api_key="test-key",
                model_id=model_id,
            )
        )
        self.response_text = response_text
        self.call_count = 0
        self.call_params: list[llm_param.LLMCallParameter] = []

    @classmethod
    def create(cls, config: llm_param.LLMConfigParameter) -> LLMClientABC:
        return cls(config.model_id or "", "created")

    async def call(self, param: llm_param.LLMCallParameter) -> LLMStreamABC:
        self.call_count += 1
        self.call_params.append(param)
        return _SingleMessageStream(self.response_text)


class _ScriptedClient(LLMClientABC):
    def __init__(self, model_id: str, responses: list[list[message.LLMStreamItem]]) -> None:
        super().__init__(
            llm_param.LLMConfigParameter(
                provider_name="test-provider",
                protocol=llm_param.LLMClientProtocol.OPENAI,
                api_key="test-key",
                model_id=model_id,
            )
        )
        self._responses = list(responses)
        self.call_count = 0

    @classmethod
    def create(cls, config: llm_param.LLMConfigParameter) -> LLMClientABC:
        return cls(config.model_id or "", [])

    async def call(self, param: llm_param.LLMCallParameter) -> LLMStreamABC:
        del param
        self.call_count += 1
        if not self._responses:
            raise RuntimeError("No scripted response available")
        return _ItemsStream(self._responses.pop(0))


class _TestProfileProvider:
    def __init__(self) -> None:
        self.model_names: list[str] = []

    def build_profile(
        self,
        llm_client: LLMClientABC,
        sub_agent_type: tools.SubAgentType | None = None,
        *,
        work_dir: Path,
    ) -> AgentProfile:
        del sub_agent_type, work_dir
        self.model_names.append(llm_client.model_name)
        return AgentProfile(llm_client=llm_client, system_prompt=None, tools=[], attachments=[])


def _consume_tool_executor(executor: ToolExecutor, tool_calls: list[ToolCallRequest]) -> asyncio.Task[None]:
    async def _runner() -> None:
        async for _ in executor.run_tools(tool_calls):
            pass

    return asyncio.create_task(_runner())


def test_sub_agent_model_override_uses_explicit_client(
    tmp_path: Path, isolated_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    del isolated_home

    async def _test() -> None:
        parent_client = _RecordingClient("main-model", "main response")
        override_client = _RecordingClient("override-model-id", "override response")
        profile_provider = _TestProfileProvider()
        parent_session = Session(work_dir=tmp_path)
        parent_agent = Agent(
            session=parent_session,
            profile=AgentProfile(llm_client=parent_client, system_prompt=None, tools=[], attachments=[]),
            model_profile_provider=profile_provider,
        )
        executor = SubAgentExecutor(
            emit_event=lambda event: asyncio.sleep(0),
            llm_clients=LLMClients(main=parent_client),
            model_profile_provider=profile_provider,
        )
        config = Config(
            main_model="main-model",
            provider_list=[
                ProviderConfig(
                    provider_name="test-provider",
                    protocol=llm_param.LLMClientProtocol.OPENAI,
                    api_key="test-key",
                    model_list=[ModelConfig(model_name="override-model", model_id="override-model-id")],
                )
            ],
        )
        monkeypatch.setattr(sub_agent_runtime, "load_config", lambda: config)
        monkeypatch.setattr(sub_agent_runtime, "create_llm_client_for_candidates", lambda candidates: override_client)

        result = await executor.run_sub_agent(
            parent_agent,
            SubAgentState(
                sub_agent_type="finder",
                sub_agent_desc="override test",
                sub_agent_prompt="hello",
                model="override-model",
            ),
        )

        spawn_entries = [
            item for item in parent_session.conversation_history if isinstance(item, message.SpawnSubAgentEntry)
        ]
        assert result.task_result == "override response"
        assert parent_client.call_count == 0
        assert override_client.call_count == 1
        assert profile_provider.model_names == ["override-model-id"]
        assert spawn_entries[0].model == "override-model"

    asyncio.run(_test())


def test_fork_context_model_override_updates_child_session_metadata(
    tmp_path: Path, isolated_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    del isolated_home

    async def _test() -> None:
        parent_client = _RecordingClient("main-model", "main response")
        override_client = _RecordingClient("gpt-4.1", "override response")
        profile_provider = _TestProfileProvider()
        parent_session = Session(work_dir=tmp_path)
        parent_session.model_name = "main-model"
        parent_agent = Agent(
            session=parent_session,
            profile=AgentProfile(
                llm_client=parent_client,
                system_prompt="parent prompt",
                tools=get_tool_schemas([tools.BASH, tools.READ, tools.EDIT, tools.WRITE]),
                attachments=[],
            ),
            model_profile_provider=profile_provider,
        )
        executor = SubAgentExecutor(
            emit_event=lambda event: asyncio.sleep(0),
            llm_clients=LLMClients(main=parent_client),
            model_profile_provider=profile_provider,
        )
        config = Config(
            main_model="main-model",
            provider_list=[
                ProviderConfig(
                    provider_name="test-provider",
                    protocol=llm_param.LLMClientProtocol.OPENAI,
                    api_key="test-key",
                    model_list=[ModelConfig(model_name="override-model", model_id="gpt-4.1")],
                )
            ],
        )
        monkeypatch.setattr(sub_agent_runtime, "load_config", lambda: config)
        monkeypatch.setattr(sub_agent_runtime, "create_llm_client_for_candidates", lambda candidates: override_client)

        result = await executor.run_sub_agent(
            parent_agent,
            SubAgentState(
                sub_agent_type="general-purpose-fork-context",
                sub_agent_desc="override test",
                sub_agent_prompt="hello",
                model="override-model",
                fork_context=True,
            ),
        )

        child_session = Session.load(result.session_id, work_dir=tmp_path)
        child_tools = override_client.call_params[0].tools
        assert child_tools is not None
        child_tool_names = {schema.name for schema in child_tools}
        assert child_session.model_name == "gpt-4.1"
        assert child_session.model_config_name == "override-model"
        assert tools.APPLY_PATCH in child_tool_names
        assert tools.EDIT not in child_tool_names
        assert tools.WRITE not in child_tool_names

    asyncio.run(_test())


def test_fork_context_file_change_summary_merges_child_delta_into_parent(tmp_path: Path, isolated_home: Path) -> None:
    del isolated_home

    async def _test() -> None:
        parent_path = str(tmp_path / "parent.py")
        child_path = str(tmp_path / "child.txt")
        child_tool_call = message.AssistantMessage(
            parts=[
                message.ToolCallPart(
                    call_id="write-child",
                    tool_name=tools.WRITE,
                    arguments_json=json.dumps({"file_path": child_path, "content": "hello\nworld\n"}),
                )
            ],
            stop_reason="tool_use",
        )
        child_final = message.AssistantMessage(
            parts=[message.TextPart(text="child done")],
            stop_reason="stop",
        )
        parent_client = _ScriptedClient("main-model", [[child_tool_call], [child_final]])
        profile_provider = _TestProfileProvider()
        parent_session = Session(work_dir=tmp_path)
        parent_session.file_change_summary.record_edited(parent_path)
        parent_session.file_change_summary.add_diff(added=5, removed=1, path=parent_path)
        parent_agent = Agent(
            session=parent_session,
            profile=AgentProfile(
                llm_client=parent_client,
                system_prompt="parent prompt",
                tools=[WriteTool.schema()],
                attachments=[],
            ),
            model_profile_provider=profile_provider,
        )
        emitted: list[events.Event] = []
        executor = SubAgentExecutor(
            emit_event=lambda event: emitted.append(event) or asyncio.sleep(0),
            llm_clients=LLMClients(main=parent_client),
            model_profile_provider=profile_provider,
        )

        result = await executor.run_sub_agent(
            parent_agent,
            SubAgentState(
                sub_agent_type="general-purpose-fork-context",
                sub_agent_desc="write child",
                sub_agent_prompt="write child file",
                fork_context=True,
            ),
        )

        assert result.task_result == "child done"
        assert parent_client.call_count == 2
        assert Path(child_path).read_text(encoding="utf-8") == "hello\nworld\n"

        summary = parent_session.file_change_summary
        assert summary.file_diffs[parent_path].added == 5
        assert summary.file_diffs[parent_path].removed == 1
        assert summary.file_diffs[child_path].added == 2
        assert summary.file_diffs[child_path].removed == 0
        assert summary.diff_lines_added == 7
        assert summary.diff_lines_removed == 1
        assert summary.edited_files == [parent_path]
        assert summary.created_files == [child_path]

        child_summary_events = [event for event in emitted if isinstance(event, events.TaskFileChangeSummaryEvent)]
        assert len(child_summary_events) == 1
        assert child_summary_events[0].summary.files[0].path == child_path

    asyncio.run(_test())


def test_fork_context_llm_fallback_preserves_current_profile(tmp_path: Path, isolated_home: Path) -> None:
    del isolated_home

    parent_client = _RecordingClient("main-model", "main response")
    replacement_client = _RecordingClient("fallback-model", "fallback response")
    profile_provider = _TestProfileProvider()
    session = Session(work_dir=tmp_path)
    session.sub_agent_state = SubAgentState(
        sub_agent_type="general-purpose-fork-context",
        sub_agent_desc="fork",
        sub_agent_prompt="prompt",
        fork_context=True,
    )
    agent = Agent(
        session=session,
        profile=AgentProfile(llm_client=parent_client, system_prompt="fork prompt", tools=[], attachments=[]),
        model_profile_provider=profile_provider,
    )

    profile = agent._apply_llm_client_change(replacement_client)  # pyright: ignore[reportPrivateUsage]

    assert profile.llm_client is replacement_client
    assert profile.system_prompt == "fork prompt"
    assert profile.tools == []
    assert profile_provider.model_names == []


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
        stream_one = _BlockingFakeStream("resp_1", "subagent one", started_one, release)
        stream_two = _BlockingFakeStream("resp_2", "subagent two", started_two, release)
        streams = iter([stream_one, stream_two])

        mock_call = AsyncMock(side_effect=lambda param: next(streams))  # pyright: ignore[reportUnknownLambdaType]

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

            stream = await mock_call(
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
            if isinstance((ui_extra := result.tool_result.ui_extra), SessionIdUIExtra)
        }

        assert len(results) == 2
        assert {result.tool_result.output_text for result in results} == {"subagent one", "subagent two"}
        assert session_ids == {"session-one", "session-two"}
        assert mock_call.call_count == 2

    asyncio.run(_test())
