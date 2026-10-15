from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

import klaude_code.agent.runtime.agent_ops as agent_ops_runtime
import klaude_code.agent.runtime.sub_agent as sub_agent_runtime
import klaude_code.tool as core_tool
from klaude_code.agent.agent import Agent
from klaude_code.agent.agent_profile import AgentProfile, load_agent_tools
from klaude_code.agent.runtime.llm import LLMClients
from klaude_code.agent.runtime.sub_agent import SubAgentLauncher
from klaude_code.agent.runtime.task_manager import TaskManager
from klaude_code.agent.session_stats import accumulate_session_usage
from klaude_code.app.runtime_facade import RuntimeFacade
from klaude_code.config.config import Config, ModelConfig, ProviderConfig
from klaude_code.control.event_bus import EventBus, EventSubscription
from klaude_code.control.user_interaction import PendingUserInteractionRequest
from klaude_code.llm.client import LLMClientABC, LLMStreamABC
from klaude_code.protocol import events, llm_param, message, op, tools, user_interaction
from klaude_code.protocol.background_task import TaskRequest
from klaude_code.protocol.models import SessionIdUIExtra, SubAgentState, TaskMetadataItem, Usage
from klaude_code.protocol.sub_agent import SubAgentResult, is_sub_agent_tool
from klaude_code.session.session import Session
from klaude_code.tool import ToolABC, WriteTool, get_tool_schemas
from klaude_code.tool.agent_tool import AgentTool
from klaude_code.tool.core.abc import ToolConcurrencyPolicy, ToolMetadata
from klaude_code.tool.core.context import TodoContext, ToolContext
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


def _make_facade_launcher(
    monkeypatch: pytest.MonkeyPatch,
    *,
    template_client: LLMClientABC,
    config: Config,
    override_client: LLMClientABC | None = None,
) -> tuple[EventBus, RuntimeFacade, SubAgentLauncher]:
    """Build a real facade whose launcher runs sub-agents through child actors."""
    monkeypatch.setattr(sub_agent_runtime, "load_config", lambda: config)
    monkeypatch.setattr(agent_ops_runtime, "load_config", lambda: config)
    monkeypatch.setattr(agent_ops_runtime, "clone_llm_clients", lambda clients: clients)
    if override_client is not None:
        monkeypatch.setattr(agent_ops_runtime, "create_llm_client_for_candidates", lambda candidates: override_client)
    event_bus = EventBus()
    facade = RuntimeFacade(event_bus, LLMClients(main=template_client))
    launcher = facade._operation_dispatcher._sub_agent_launcher  # pyright: ignore[reportPrivateUsage]
    return event_bus, facade, launcher


def _drain_subscription_events(subscription: EventSubscription) -> list[events.Event]:
    collected: list[events.Event] = []
    queue = subscription._queue  # pyright: ignore[reportPrivateUsage]
    while True:
        try:
            item = queue.get_nowait()
        except asyncio.QueueEmpty:
            return collected
        if isinstance(item, events.EventEnvelope):
            collected.append(item.event)


async def _run_background_sub_agent(
    facade: RuntimeFacade, launcher: SubAgentLauncher, parent: Agent, state: SubAgentState
) -> SubAgentResult:
    task = await launcher.start_sub_agent(parent, state)
    response = await facade.task_manager.manage(
        parent.session.id, parent.session.work_dir, TaskRequest(action="wait", task_id=task.ref.task_id)
    )
    result = response.tasks[0].result
    assert result is not None
    return SubAgentResult(
        task_result=response.output,
        session_id=task.ref.session_id or "",
        error=result.error,
        task_metadata=result.metadata,
        file_changes=result.file_changes,
    )


@pytest.mark.parametrize("force", [False, True])
def test_collector_pins_owner_across_close_reconfigure_and_reload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, force: bool
) -> None:
    async def test() -> None:
        started, release = asyncio.Event(), asyncio.Event()
        input_path = tmp_path / "input.txt"
        input_path.write_text("child input")

        class ChildStream(_BlockingFakeStream):
            async def _iterate(self) -> AsyncGenerator[message.LLMStreamItem]:
                started.set()
                await release.wait()
                yield message.AssistantMessage(
                    parts=message.text_parts_from_str("child report"),
                    stop_reason="stop",
                )

        class ChildClient(_RecordingClient):
            async def call(self, param: llm_param.LLMCallParameter) -> LLMStreamABC:
                self.call_count += 1
                if self.call_count == 1:
                    return _ItemsStream(
                        [
                            message.AssistantMessage(
                                parts=[
                                    message.ToolCallPart(
                                        call_id="read-input",
                                        tool_name=tools.READ,
                                        arguments_json=json.dumps({"file_path": str(input_path)}),
                                    )
                                ],
                                stop_reason="tool_use",
                                usage=Usage(input_tokens=11, input_cost=1),
                            )
                        ]
                    )
                return ChildStream("child", "report", started, release)

        parent_client, child_client = _RecordingClient("parent", "parent done"), ChildClient("child", "")
        config = Config(
            provider_list=[
                ProviderConfig(
                    provider_name="test",
                    protocol=llm_param.LLMClientProtocol.OPENAI,
                    api_key="test-key",
                    model_list=[ModelConfig(model_name="child-model", model_id="child")],
                )
            ]
        )
        _event_bus, facade, launcher = _make_facade_launcher(
            monkeypatch, template_client=parent_client, config=config, override_client=child_client
        )
        handler = facade._operation_dispatcher._agent_operation_handler
        monkeypatch.setattr(handler, "_schedule_prompt_suggestion", lambda *_args: None)
        monkeypatch.setattr(handler, "_schedule_session_title_refresh", lambda *_args: None)
        session = Session(work_dir=tmp_path)
        session.ensure_meta_exists()
        parent = Agent(
            session,
            AgentProfile(llm_client=parent_client, system_prompt=None, tools=[], attachments=[]),
            task_manager=facade.task_manager,
        )
        actor = facade.session_registry.ensure_session_actor(session.id)
        actor.set_agent(parent)
        actor.set_llm_clients(LLMClients(main=parent_client))
        try:
            task = await launcher.start_sub_agent(
                parent,
                SubAgentState(
                    sub_agent_type="general-purpose",
                    sub_agent_desc="close race",
                    sub_agent_prompt="work",
                    model="child-model",
                ),
            )
            await asyncio.wait_for(started.wait(), 3)
            assert actor.is_idle() and actor.has_lifecycle_pins()
            assert await facade.session_registry.reclaim_idle_sessions(idle_for_seconds=0) == []
            assert not await facade.close_session(session.id)
            # Reconfiguration must reuse the pinned session, not load a second owner.
            await handler.init_agent(session.id, work_dir=tmp_path, suppress_welcome=True)
            assert actor.get_agent() is parent
            # A lifecycle pin does not reserve the root slot.
            await facade.submit_and_wait(
                op.RunAgentOperation(
                    session_id=session.id, input=message.UserInputPayload(text="new turn while child runs")
                )
            )
            async with asyncio.timeout(3):
                while actor.has_active_root_task():
                    await asyncio.sleep(0)
            assert parent_client.call_count == 1 and not release.is_set()
            if force:
                assert await facade.close_session(session.id, force=True)
                assert not actor.has_lifecycle_pins()
                assert not facade.task_manager.active_owner_ids()
                assert not facade.task_manager._collectors
            else:
                release.set()
                await facade.task_manager.manage(
                    session.id, tmp_path, TaskRequest(action="wait", task_id=task.ref.task_id)
                )
                assert not actor.has_lifecycle_pins()
                assert await facade.close_session(session.id)
            await handler.init_agent(session.id, work_dir=tmp_path, suppress_welcome=True)
            reloaded_actor = facade.session_registry.get_session_actor(session.id)
            assert reloaded_actor is not None
            reloaded = reloaded_actor.get_agent()
            assert reloaded is not None and reloaded.session is not session
            await facade.task_manager.settle_agent_results(reloaded.session)
            await facade.task_manager.settle_agent_results(reloaded.session)
            disk = Session.load(session.id, work_dir=tmp_path)
            assert accumulate_session_usage(disk).total.total_cost == 1
            assert (
                len(
                    [
                        item
                        for item in disk.conversation_history
                        if isinstance(item, TaskMetadataItem) and item.background_task_id == task.ref.task_id
                    ]
                )
                == 1
            )
            assert not any(not collector.done() for collector in facade.task_manager._collectors.values())
        finally:
            release.set()
            await facade.stop()

    asyncio.run(test())


@pytest.mark.parametrize("switch", ["clear", "fork"])
def test_session_switch_keeps_manage_tasks_available(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, switch: str
) -> None:
    async def test() -> None:
        client = _ScriptedClient(
            "parent",
            [
                [
                    message.AssistantMessage(
                        parts=[
                            message.ToolCallPart(
                                call_id="list-tasks", tool_name=tools.MANAGE_TASKS, arguments_json='{"action":"list"}'
                            )
                        ],
                        stop_reason="tool_use",
                    )
                ],
                [message.AssistantMessage(parts=message.text_parts_from_str("done"), stop_reason="stop")],
            ],
        )
        _event_bus, facade, _ = _make_facade_launcher(
            monkeypatch, template_client=client, config=Config(provider_list=[])
        )
        handler = facade._operation_dispatcher._agent_operation_handler
        provider = _TestProfileProvider()
        monkeypatch.setattr(handler, "_model_profile_provider", provider)
        original_build = provider.build_profile

        def build(llm_client: LLMClientABC, *, work_dir: Path) -> AgentProfile:
            profile = original_build(llm_client, work_dir=work_dir)
            return AgentProfile(
                llm_client=profile.llm_client,
                system_prompt=profile.system_prompt,
                tools=get_tool_schemas([tools.MANAGE_TASKS]),
                attachments=profile.attachments,
            )

        monkeypatch.setattr(provider, "build_profile", build)
        session = Session(work_dir=tmp_path)
        actor = facade.session_registry.ensure_session_actor(session.id)
        actor.set_agent(Agent(session, build(client, work_dir=tmp_path)))
        actor.set_llm_clients(LLMClients(main=client))
        try:
            if switch == "clear":
                await handler.clear_session(session.id)
                agents = [item.get_agent() for item in facade.session_registry.list_session_actors()]
                new_agent = next(item for item in agents if item is not None and item.session.id != session.id)
            else:
                fork = session.fork()
                fork.append_history([message.UserMessage(parts=message.text_parts_from_str("fork seed"))])
                await fork.wait_for_flush()
                await handler.fork_and_switch_session(session.id, fork.id, session.id[:8])
                new_actor = facade.session_registry.get_session_actor(fork.id)
                assert new_actor is not None
                new_agent = new_actor.get_agent()
                assert new_agent is not None
            assert new_agent.task_manager is facade.task_manager
            _ = [event async for event in new_agent.run_task(message.UserInputPayload(text="list tasks"))]
            results = [
                item
                for item in new_agent.session.conversation_history
                if isinstance(item, message.ToolResultMessage) and item.tool_name == tools.MANAGE_TASKS
            ]
            assert len(results) == 1 and results[0].status == "success"
            assert json.loads(results[0].output_text.split("\n", 1)[1])["tasks"] == []
        finally:
            await facade.stop()

    asyncio.run(test())


def test_default_async_parent_interrupt_and_stop_owned_children(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def test() -> None:
        parent_waiting, parent_release = asyncio.Event(), asyncio.Event()
        child_started, child_release = asyncio.Event(), asyncio.Event()

        class ParentClient(_RecordingClient):
            async def call(self, param: llm_param.LLMCallParameter) -> LLMStreamABC:
                self.call_count += 1
                if self.call_count == 1:
                    return _ItemsStream(
                        [
                            message.AssistantMessage(
                                parts=[
                                    message.ToolCallPart(
                                        call_id=f"spawn-{index}",
                                        tool_name=tools.AGENT,
                                        arguments_json=json.dumps(
                                            {"description": f"child {index}", "prompt": "work", "model": "child-model"}
                                        ),
                                    )
                                    for index in range(2)
                                ],
                                stop_reason="tool_use",
                            )
                        ]
                    )
                return _BlockingFakeStream("parent", "parent done", parent_waiting, parent_release)

        class ChildClient(_RecordingClient):
            async def call(self, param: llm_param.LLMCallParameter) -> LLMStreamABC:
                self.call_count += 1

                class PartialStream(_BlockingFakeStream):
                    def get_partial_message(self) -> message.AssistantMessage | None:
                        return message.AssistantMessage(parts=[message.TextPart(text="partial child output")])

                return PartialStream("child", "child report", child_started, child_release)

        parent_client, child_client = ParentClient("parent", ""), ChildClient("child", "")
        config = Config(
            provider_list=[
                ProviderConfig(
                    provider_name="test-provider",
                    protocol=llm_param.LLMClientProtocol.OPENAI,
                    api_key="test-key",
                    model_list=[ModelConfig(model_name="child-model", model_id="child")],
                )
            ]
        )
        event_bus, facade, _ = _make_facade_launcher(
            monkeypatch, template_client=parent_client, config=config, override_client=child_client
        )
        handler = facade._operation_dispatcher._agent_operation_handler
        monkeypatch.setattr(handler, "_schedule_session_title_refresh", lambda *_args: None)
        monkeypatch.setattr(handler, "_schedule_prompt_suggestion", lambda *_args: None)
        session = Session(work_dir=tmp_path)
        parent = Agent(
            session,
            AgentProfile(
                llm_client=parent_client,
                system_prompt=None,
                attachments=[],
                tools=get_tool_schemas([tools.AGENT, tools.MANAGE_TASKS]),
            ),
            task_manager=facade.task_manager,
        )
        actor = facade.session_registry.ensure_session_actor(session.id)
        actor.set_agent(parent)
        actor.set_llm_clients(LLMClients(main=parent_client))
        try:
            await facade.submit(
                op.RunAgentOperation(session_id=session.id, input=message.UserInputPayload(text="delegate"))
            )
            await asyncio.wait_for(parent_waiting.wait(), 3)
            await asyncio.wait_for(child_started.wait(), 3)
            async with asyncio.timeout(3):
                while child_client.call_count < 2:
                    await asyncio.sleep(0)
            tasks = await facade.task_manager.list_tasks(session.id, tmp_path)
            assert len(tasks) == 2 and all(task.status == "running" for task in tasks)
            tool_results = [
                item for item in session.conversation_history if isinstance(item, message.ToolResultMessage)
            ]
            assert len(tool_results) == 2
            assert all(
                "task_id=" in item.output_text and "child report" not in item.output_text for item in tool_results
            )
            assert all(item.task_metadata is None for item in tool_results)
            await facade.submit_and_wait(op.InterruptOperation(session_id=session.id))
            assert actor.snapshot().is_idle
            assert all(task.status == "running" for task in await facade.task_manager.list_tasks(session.id, tmp_path))
            assert child_client.call_count == 2 and not child_release.is_set()
            wait_client = _ScriptedClient(
                "parent",
                [
                    [
                        message.AssistantMessage(
                            parts=[
                                message.ToolCallPart(
                                    call_id="wait-child",
                                    tool_name=tools.MANAGE_TASKS,
                                    arguments_json=TaskRequest(
                                        action="wait", task_id=tasks[0].ref.task_id
                                    ).model_dump_json(),
                                )
                            ],
                            stop_reason="tool_use",
                        )
                    ],
                    [message.AssistantMessage(parts=[message.TextPart(text="steered")], stop_reason="stop")],
                ],
            )
            parent.set_model_profile(
                AgentProfile(
                    llm_client=wait_client,
                    system_prompt=None,
                    attachments=[],
                    tools=get_tool_schemas([tools.MANAGE_TASKS]),
                )
            )
            subscription = event_bus.subscribe(session.id)
            wait_run = op.RunAgentOperation(
                session_id=session.id, input=message.UserInputPayload(text="wait for child")
            )
            await facade.submit(wait_run)
            async with asyncio.timeout(3):
                async for envelope in subscription:
                    if (
                        isinstance(envelope.event, events.ToolCallEvent)
                        and envelope.event.tool_name == tools.MANAGE_TASKS
                    ):
                        break
            await facade.submit_and_wait(
                op.FollowUpAgentOperation(
                    session_id=session.id, input=message.UserInputPayload(text="change direction")
                )
            )
            await asyncio.wait_for(facade.wait_for(wait_run.id), 3)
            waits = [
                item
                for item in session.conversation_history
                if isinstance(item, message.ToolResultMessage) and item.call_id == "wait-child"
            ]
            assert len(waits) == 1 and "interrupted-wait; still-running" in waits[0].output_text
            assert all(task.status == "running" for task in await facade.task_manager.list_tasks(session.id, tmp_path))
            child_id = tasks[0].ref.session_id
            assert child_id is not None
            interaction = asyncio.create_task(
                facade._operation_dispatcher.request_user_interaction(
                    PendingUserInteractionRequest(
                        request_id="child-question",
                        session_id=child_id,
                        source="tool",
                        tool_call_id="question",
                        payload=user_interaction.AskUserQuestionRequestPayload(
                            questions=[
                                user_interaction.AskUserQuestionQuestion(
                                    id="q",
                                    header="choice",
                                    question="Proceed?",
                                    options=[
                                        user_interaction.AskUserQuestionOption(id="a", label="A", description="first"),
                                        user_interaction.AskUserQuestionOption(id="b", label="B", description="second"),
                                    ],
                                )
                            ]
                        ),
                    )
                )
            )
            await asyncio.sleep(0)
            child_actor = facade.session_registry.get_session_actor(child_id)
            assert child_actor is not None and child_actor.pending_request_count() == 1
            peer_session = Session(work_dir=tmp_path)
            peer_actor = facade.session_registry.ensure_session_actor(peer_session.id)
            peer_client = ChildClient("peer", "")
            peer_actor.set_agent(
                Agent(peer_session, AgentProfile(llm_client=peer_client, system_prompt=None, tools=[], attachments=[]))
            )
            peer_actor.set_llm_clients(LLMClients(main=peer_client))
            await facade.submit(
                op.RunAgentOperation(
                    session_id=peer_session.id, input=message.UserInputPayload(text="independent peer")
                )
            )
            async with asyncio.timeout(3):
                while peer_actor.snapshot().active_root_task is None:
                    await asyncio.sleep(0)
            shell = await facade.shell_task_manager.start(
                session_id=session.id,
                work_dir=tmp_path,
                command="sleep 30",
                description="independent shell",
                timeout_ms=None,
                env={},
                background=True,
            )
            await asyncio.wait_for(facade.submit_and_wait(op.StopSubAgentsOperation(session_id=session.id)), 3)
            snapshots = await facade.task_manager.list_tasks(session.id, tmp_path)
            assert all(task.status == "stopped" for task in snapshots if task.ref.kind == "agent")
            assert next(task for task in snapshots if task.ref.task_id == shell.task_id).status == "running"
            assert await facade.task_manager.pending_results(session.id, tmp_path) == []
            assert interaction.cancelled() and child_actor.pending_request_count() == 0
            assert peer_actor.snapshot().active_root_task is not None
            assert all(
                facade.session_registry.get_session_actor(task.ref.session_id or "") is not None for task in tasks
            )
            # A subsequent explicit run is independent of the stopped run generation.
            child_release.set()
            child_id = tasks[0].ref.session_id
            assert child_id is not None
            await facade.submit_and_wait(
                op.RunAgentOperation(session_id=child_id, input=message.UserInputPayload(text="resume explicitly"))
            )
            assert (await facade.task_manager.list_tasks(session.id, tmp_path))[0].status == "stopped"
            assert await facade.task_manager.pending_results(session.id, tmp_path) == []
        finally:
            await facade.stop()

    asyncio.run(test())


def test_collector_recovers_report_and_metadata_after_event_overflow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def test() -> None:
        client = _ScriptedClient(
            "model",
            [
                [
                    *[message.AssistantTextDelta(content="part") for _ in range(20)],
                    message.AssistantMessage(
                        parts=[message.TextPart(text="final report")],
                        stop_reason="stop",
                        usage=Usage(input_tokens=10, output_tokens=5, output_cost=0.25),
                    ),
                ]
            ],
        )
        event_bus, facade, launcher = _make_facade_launcher(
            monkeypatch, template_client=client, config=Config(provider_list=[])
        )
        original_subscribe = event_bus.subscribe

        def subscribe(session_id: str | None = None) -> EventSubscription:
            subscription = original_subscribe(session_id)
            if session_id is not None:
                monkeypatch.setattr(subscription._queue, "qsize", lambda: 1024)
            return subscription

        monkeypatch.setattr(event_bus, "subscribe", subscribe)
        parent = Agent(
            Session(work_dir=tmp_path), AgentProfile(llm_client=client, system_prompt=None, tools=[], attachments=[])
        )
        try:
            result = await asyncio.wait_for(
                _run_background_sub_agent(
                    facade,
                    launcher,
                    parent,
                    SubAgentState(sub_agent_type="finder", sub_agent_desc="overflow", sub_agent_prompt="report"),
                ),
                3,
            )
            assert not result.error and result.task_result == "final report"
            assert result.task_metadata is not None and result.task_metadata.usage is not None
            assert result.task_metadata.usage.total_cost == 0.25
            metadata = [item for item in parent.session.conversation_history if isinstance(item, TaskMetadataItem)]
            assert len(metadata) == 1 and len(metadata[0].sub_agent_task_metadata) == 1
        finally:
            await facade.stop()

    asyncio.run(test())


def test_sub_agent_model_override_uses_explicit_client(
    tmp_path: Path, isolated_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    del isolated_home

    async def _test() -> None:
        parent_client = _RecordingClient("main-model", "main response")
        override_client = _RecordingClient("override-model-id", "override response")
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
        _event_bus, facade, launcher = _make_facade_launcher(
            monkeypatch,
            template_client=parent_client,
            config=config,
            override_client=override_client,
        )
        try:
            parent_session = Session(work_dir=tmp_path)
            parent_agent = Agent(
                session=parent_session,
                profile=AgentProfile(llm_client=parent_client, system_prompt=None, tools=[], attachments=[]),
            )

            result = await _run_background_sub_agent(
                facade,
                launcher,
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
            assert result.error is False
            assert parent_client.call_count == 0
            assert override_client.call_count == 1
            assert spawn_entries[0].model == "override-model"

            child_session = Session.load(result.session_id, work_dir=tmp_path)
            assert child_session.parent_session_id == parent_session.id
            assert child_session.spawn_kind == "subagent"
            assert child_session.agent_type == "finder"
            assert child_session.model_config_name == "override-model"
        finally:
            await facade.stop()

    asyncio.run(_test())


def test_fork_context_model_override_updates_child_session_metadata(
    tmp_path: Path, isolated_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    del isolated_home

    async def _test() -> None:
        parent_client = _RecordingClient("main-model", "main response")
        override_client = _RecordingClient("gpt-4.1", "override response")
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
        _event_bus, facade, launcher = _make_facade_launcher(
            monkeypatch,
            template_client=parent_client,
            config=config,
            override_client=override_client,
        )
        try:
            parent_session = Session(work_dir=tmp_path)
            parent_session.model_name = "main-model"
            parent_session.prompt_cache_key = "parent-cache-lineage"
            parent_agent = Agent(
                session=parent_session,
                profile=AgentProfile(
                    llm_client=parent_client,
                    system_prompt="parent prompt",
                    tools=[],
                    attachments=[],
                ),
            )

            result = await _run_background_sub_agent(
                facade,
                launcher,
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
            assert child_session.prompt_cache_key == "parent-cache-lineage"
            assert child_session.parent_session_id == parent_session.id
            assert override_client.call_params[0].prompt_cache_key == "parent-cache-lineage"
            assert tools.APPLY_PATCH in child_tool_names
            assert tools.EDIT not in child_tool_names
            assert tools.WRITE not in child_tool_names
        finally:
            await facade.stop()

    asyncio.run(_test())


def test_fork_context_file_change_summary_merges_child_delta_into_parent(
    tmp_path: Path, isolated_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
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
            usage=Usage(input_tokens=10, output_tokens=5, input_cost=0.125),
        )
        parent_client = _ScriptedClient("main-model", [[child_tool_call], [child_final]])
        config = Config(main_model="main-model", provider_list=[])
        event_bus, facade, launcher = _make_facade_launcher(
            monkeypatch,
            template_client=parent_client,
            config=config,
        )
        try:
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
            )
            subscription = event_bus.subscribe(None)

            result = await _run_background_sub_agent(
                facade,
                launcher,
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
            await facade.task_manager.settle_agent_results(parent_session)
            await facade.task_manager.settle_agent_results(parent_session)
            accounting = [
                item
                for item in parent_session.conversation_history
                if isinstance(item, TaskMetadataItem) and item.background_task_id is not None
            ]
            assert len(accounting) == 1
            assert accounting[0].sub_agent_task_metadata[0].usage is not None
            assert accounting[0].sub_agent_task_metadata[0].usage.total_cost == 0.125
            restored_parent = Session.load(parent_session.id, work_dir=tmp_path)
            restored_manager = TaskManager(None, AsyncMock(), AsyncMock())
            await restored_manager.settle_agent_results(restored_parent)
            assert restored_parent.file_change_summary == summary
            stats = accumulate_session_usage(restored_parent)
            assert stats.total.total_cost == 0.125
            assert stats.task_count == 0
            replayed_accounting = [
                event
                for event in restored_parent.get_history_item()
                if isinstance(event, events.TaskMetadataEvent) and event.session_id == restored_parent.id
            ]
            assert len(replayed_accounting) == 1
            assert replayed_accounting[0].metadata.background_task_id == accounting[0].background_task_id
            assert not any(
                isinstance(event, events.TaskFinishEvent) and event.session_id == restored_parent.id
                for event in restored_parent.get_history_item()
            )
            assert (
                len(
                    [
                        item
                        for item in restored_parent.conversation_history
                        if isinstance(item, TaskMetadataItem) and item.background_task_id is not None
                    ]
                )
                == 1
            )

            emitted = _drain_subscription_events(subscription)
            child_summary_events = [event for event in emitted if isinstance(event, events.TaskFileChangeSummaryEvent)]
            assert len(child_summary_events) == 1
            assert child_summary_events[0].summary.files[0].path == child_path
            task_starts = [
                event
                for event in emitted
                if isinstance(event, events.TaskStartEvent) and event.session_id == result.session_id
            ]
            assert task_starts and task_starts[0].parent_session_id == parent_session.id
        finally:
            await facade.stop()

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
        ) -> SubAgentResult:
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
