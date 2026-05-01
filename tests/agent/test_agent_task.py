from __future__ import annotations

import asyncio
import json
import subprocess
from collections.abc import Coroutine
from pathlib import Path
from typing import Any, ClassVar

import pytest

import klaude_code.agent.runtime.llm as runtime_llm
import klaude_code.agent.task as task_module
from klaude_code.agent.agent_profile import AgentProfile
from klaude_code.agent.runtime.llm import FallbackLLMClient
from klaude_code.agent.task import SessionContext, TaskExecutionContext, TaskExecutor
from klaude_code.config.config import ModelConfigCandidate
from klaude_code.llm.client import LLMClientABC, LLMStreamABC
from klaude_code.llm.usage import MetadataTracker, error_stream_items
from klaude_code.prompts.messages import EMPTY_RESPONSE_CONTINUATION_PROMPT
from klaude_code.protocol import events, llm_param, message
from klaude_code.protocol.models import TaskMetadataItem, Usage
from klaude_code.session.session import Session
from klaude_code.tool.core.abc import ToolABC
from klaude_code.tool.core.context import ToolContext, build_todo_context
from tests.agent.agent_harness import ScriptedLLMStream, create_harness


def arun[T](coro: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _isolate_home(isolated_home: Path) -> Path:  # pyright: ignore[reportUnusedFunction]
    return isolated_home


# ---------------------------------------------------------------------------
# Mock tools
# ---------------------------------------------------------------------------


class MockEchoTool(ToolABC):
    calls: ClassVar[list[str]] = []

    @classmethod
    def schema(cls) -> llm_param.ToolSchema:
        return llm_param.ToolSchema(
            name="echo",
            type="function",
            description="Echo tool",
            parameters={"type": "object", "properties": {"text": {"type": "string"}}},
        )

    @classmethod
    async def call(cls, arguments: str, context: ToolContext) -> message.ToolResultMessage:
        args = json.loads(arguments)
        cls.calls.append(args["text"])
        return message.ToolResultMessage(
            status="success",
            output_text=f"echo: {args['text']}",
        )


class MockUpperTool(ToolABC):
    calls: ClassVar[list[str]] = []

    @classmethod
    def schema(cls) -> llm_param.ToolSchema:
        return llm_param.ToolSchema(
            name="upper",
            type="function",
            description="Uppercase tool",
            parameters={"type": "object", "properties": {"text": {"type": "string"}}},
        )

    @classmethod
    async def call(cls, arguments: str, context: ToolContext) -> message.ToolResultMessage:
        args = json.loads(arguments)
        cls.calls.append(args["text"])
        return message.ToolResultMessage(
            status="success",
            output_text=args["text"].upper(),
        )


class MockChangeTool(ToolABC):
    @classmethod
    def schema(cls) -> llm_param.ToolSchema:
        return llm_param.ToolSchema(
            name="change",
            type="function",
            description="Record a file change",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "added": {"type": "integer"},
                    "removed": {"type": "integer"},
                    "created": {"type": "boolean"},
                    "deleted": {"type": "boolean"},
                },
                "required": ["path"],
            },
        )

    @classmethod
    async def call(cls, arguments: str, context: ToolContext) -> message.ToolResultMessage:
        args = json.loads(arguments)
        path = str(args["path"])
        if context.file_change_summary is not None:
            if args.get("deleted", False):
                context.file_change_summary.record_deleted(path)
            elif args.get("created", False):
                context.file_change_summary.record_created(path)
            else:
                context.file_change_summary.record_edited(path)
            context.file_change_summary.add_diff(
                added=int(args.get("added", 0)),
                removed=int(args.get("removed", 0)),
                path=path,
            )
        return message.ToolResultMessage(status="success", output_text=f"changed {path}")


class MockFilesystemChangeTool(ToolABC):
    @classmethod
    def schema(cls) -> llm_param.ToolSchema:
        return llm_param.ToolSchema(
            name="fs_change",
            type="function",
            description="Write a file",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                    "record": {"type": "boolean"},
                },
                "required": ["path", "content"],
            },
        )

    @classmethod
    async def call(cls, arguments: str, context: ToolContext) -> message.ToolResultMessage:
        args = json.loads(arguments)
        path = Path(str(args["path"]))
        exists = path.exists()
        content = str(args["content"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        if args.get("record", False) and context.file_change_summary is not None:
            if exists:
                context.file_change_summary.record_edited(str(path))
            else:
                context.file_change_summary.record_created(str(path))
            context.file_change_summary.add_diff(added=len(content.splitlines()), removed=0, path=str(path))
        return message.ToolResultMessage(status="success", output_text=f"changed {path}")


class ConfiguredScriptedClient(LLMClientABC):
    def __init__(self, config: llm_param.LLMConfigParameter, responses: list[list[message.LLMStreamItem]]) -> None:
        super().__init__(config)
        self._responses = list(responses)
        self.calls: list[llm_param.LLMCallParameter] = []

    @classmethod
    def create(cls, config: llm_param.LLMConfigParameter) -> LLMClientABC:
        return cls(config, [])

    async def call(self, param: llm_param.LLMCallParameter) -> LLMStreamABC:
        self.calls.append(param)
        if not self._responses:
            raise RuntimeError("ConfiguredScriptedClient has no queued response")
        return ScriptedLLMStream(self._responses.pop(0))


@pytest.fixture(autouse=True)
def _reset_tool_calls() -> None:  # pyright: ignore[reportUnusedFunction]
    MockEchoTool.calls = []
    MockUpperTool.calls = []


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_usage() -> Usage:
    return Usage(
        input_tokens=10,
        output_tokens=5,
        context_size=15,
        context_limit=200_000,
        model_name="fake-model",
        provider="test",
    )


def _text_assistant_message(text: str, *, stop_reason: message.StopReason = "stop") -> message.AssistantMessage:
    return message.AssistantMessage(
        parts=[message.TextPart(text=text)],
        stop_reason=stop_reason,
        usage=_make_usage(),
    )


def _tool_call_assistant_message(
    calls: list[tuple[str, str, str]],
    *,
    text: str = "",
) -> message.AssistantMessage:
    """Build an AssistantMessage with tool calls.

    Args:
        calls: List of (tool_name, call_id, arguments_json) tuples.
        text: Optional text content before tool calls.
    """
    parts: list[message.Part] = []
    if text:
        parts.append(message.TextPart(text=text))
    for tool_name, call_id, args_json in calls:
        parts.append(message.ToolCallPart(call_id=call_id, tool_name=tool_name, arguments_json=args_json))
    return message.AssistantMessage(
        parts=parts,
        stop_reason="tool_use",
        usage=_make_usage(),
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_basic_text_response(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Basic prompt -> text response."""
    project_dir = tmp_path / "project"
    project_dir.mkdir()

    async def _test() -> None:
        harness = await create_harness(work_dir=project_dir, monkeypatch=monkeypatch)
        harness.fake_llm.enqueue(
            message.AssistantTextDelta(content="hello world"),
            _text_assistant_message("hello world"),
        )

        collected = await harness.run_task("hi")

        # History: user + assistant
        assert harness.get_user_texts() == ["hi"]
        assert harness.get_assistant_texts() == ["hello world"]

        # TaskFinishEvent present
        finish_events = [e for e in collected if isinstance(e, events.TaskFinishEvent)]
        assert len(finish_events) == 1

    arun(_test())


def test_tool_call_then_followup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Tool call turn -> follow-up text response."""
    project_dir = tmp_path / "project"
    project_dir.mkdir()

    async def _test() -> None:
        harness = await create_harness(
            work_dir=project_dir,
            tools={"echo": MockEchoTool},
            monkeypatch=monkeypatch,
        )

        # Turn 1: tool call
        harness.fake_llm.enqueue(
            _tool_call_assistant_message([("echo", "call_1", '{"text":"hello"}')]),
        )
        # Turn 2: text response
        harness.fake_llm.enqueue(
            message.AssistantTextDelta(content="done"),
            _text_assistant_message("done"),
        )

        collected = await harness.run_task("run echo")

        # Check history: user, assistant(tool_call), tool_result, assistant(text)
        history = harness.get_history_messages()
        msg_types = [
            type(h).__name__
            for h in history
            if isinstance(h, (message.UserMessage, message.AssistantMessage, message.ToolResultMessage))
        ]
        assert msg_types == ["UserMessage", "AssistantMessage", "ToolResultMessage", "AssistantMessage"]

        # Tool was executed
        assert MockEchoTool.calls == ["hello"]

        # Tool result in history
        tool_results = [h for h in history if isinstance(h, message.ToolResultMessage)]
        assert len(tool_results) == 1
        assert "echo: hello" in tool_results[0].output_text

        # Two TurnStartEvent and two TurnEndEvent
        turn_starts = [e for e in collected if isinstance(e, events.TurnStartEvent)]
        turn_ends = [e for e in collected if isinstance(e, events.TurnEndEvent)]
        assert len(turn_starts) == 2
        assert len(turn_ends) == 2

    arun(_test())


def test_multiple_tool_calls_in_one_response(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Multiple tool calls in one response."""
    project_dir = tmp_path / "project"
    project_dir.mkdir()

    async def _test() -> None:
        harness = await create_harness(
            work_dir=project_dir,
            tools={"echo": MockEchoTool, "upper": MockUpperTool},
            monkeypatch=monkeypatch,
        )

        # Turn 1: two tool calls
        harness.fake_llm.enqueue(
            _tool_call_assistant_message(
                [
                    ("echo", "call_1", '{"text":"foo"}'),
                    ("upper", "call_2", '{"text":"bar"}'),
                ]
            ),
        )
        # Turn 2: text response
        harness.fake_llm.enqueue(
            message.AssistantTextDelta(content="all done"),
            _text_assistant_message("all done"),
        )

        await harness.run_task("do both")

        # Both tools executed
        assert MockEchoTool.calls == ["foo"]
        assert MockUpperTool.calls == ["bar"]

        # Two tool results in history
        tool_results = [h for h in harness.get_history_messages() if isinstance(h, message.ToolResultMessage)]
        assert len(tool_results) == 2

    arun(_test())


def test_stream_error_triggers_retry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Stream error triggers retry, final result recovered."""
    project_dir = tmp_path / "project"
    project_dir.mkdir()

    async def _test() -> None:
        harness = await create_harness(work_dir=project_dir, monkeypatch=monkeypatch)

        # Turn 1: stream error
        harness.fake_llm.enqueue(
            message.StreamErrorItem(error="network error"),
        )
        # Turn 2: recovered
        harness.fake_llm.enqueue(
            message.AssistantTextDelta(content="recovered"),
            _text_assistant_message("recovered"),
        )

        collected = await harness.run_task("try again")

        # ErrorEvent emitted with retry info
        error_events = [e for e in collected if isinstance(e, events.ErrorEvent)]
        assert len(error_events) >= 1
        assert error_events[0].can_retry is True

        # Final assistant text
        assert "recovered" in harness.get_assistant_texts()

    arun(_test())


def test_stream_error_retry_includes_previous_tool_turn_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Retry after a stream error sees prior assistant tool call and tool result."""
    project_dir = tmp_path / "project"
    project_dir.mkdir()

    def has_previous_tool_turn(items: list[message.HistoryEvent]) -> bool:
        has_assistant_tool_call = any(
            isinstance(item, message.AssistantMessage)
            and any(
                isinstance(part, message.ToolCallPart) and part.call_id == "call_1" and part.tool_name == "echo"
                for part in item.parts
            )
            for item in items
        )
        has_tool_result = any(
            isinstance(item, message.ToolResultMessage)
            and item.call_id == "call_1"
            and item.tool_name == "echo"
            and "echo: hello" in item.output_text
            for item in items
        )
        return has_assistant_tool_call and has_tool_result

    async def _test() -> None:
        harness = await create_harness(
            work_dir=project_dir,
            tools={"echo": MockEchoTool},
            monkeypatch=monkeypatch,
        )
        captured_inputs: list[list[message.HistoryEvent]] = []

        # Turn 1: successful tool call writes AssistantMessage + ToolResultMessage.
        harness.fake_llm.enqueue(
            _tool_call_assistant_message([("echo", "call_1", '{"text":"hello"}')]),
        )

        def stream_error(param: llm_param.LLMCallParameter) -> list[message.LLMStreamItem]:
            captured_inputs.append(list(param.input))
            return [message.StreamErrorItem(error="network error")]

        def recover(param: llm_param.LLMCallParameter) -> list[message.LLMStreamItem]:
            captured_inputs.append(list(param.input))
            return [
                message.AssistantTextDelta(content="recovered"),
                _text_assistant_message("recovered"),
            ]

        # Turn 2 fails once, then the failed turn is retried.
        harness.fake_llm.enqueue_factory(stream_error)
        harness.fake_llm.enqueue_factory(recover)

        await harness.run_task("run echo then recover")

        assert len(captured_inputs) == 2
        assert has_previous_tool_turn(captured_inputs[0])
        assert has_previous_tool_turn(captured_inputs[1])
        assert "recovered" in harness.get_assistant_texts()

    arun(_test())


def test_fallback_model_rebuilds_profile_and_replays_warning(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project_dir = tmp_path / "project"
    project_dir.mkdir()

    async def _test() -> None:
        def _never_compact(*, session: Session, config: Any, llm_config: Any) -> bool:
            del session, config, llm_config
            return False

        monkeypatch.setattr(task_module, "should_compact_threshold", _never_compact)

        first_config = llm_param.LLMConfigParameter(
            provider_name="openai",
            protocol=llm_param.LLMClientProtocol.OPENAI,
            model_id="gpt-5.5",
        )
        second_config = llm_param.LLMConfigParameter(
            provider_name="openrouter",
            protocol=llm_param.LLMClientProtocol.OPENAI,
            model_id="gpt-5.4",
        )
        first_client = ConfiguredScriptedClient(
            first_config,
            [
                error_stream_items(
                    MetadataTracker(llm_param.Cost()),
                    error="RateLimitError insufficient_quota: credits exhausted",
                )
            ],
        )
        second_client = ConfiguredScriptedClient(
            second_config,
            [[message.AssistantTextDelta(content="recovered"), _text_assistant_message("recovered")]],
        )

        def _create_llm_client(config: llm_param.LLMConfigParameter) -> LLMClientABC:
            return first_client if config.provider_name == "openai" else second_client

        monkeypatch.setattr(runtime_llm, "create_llm_client", _create_llm_client)

        fallback_client = FallbackLLMClient(
            [
                ModelConfigCandidate(
                    selector="gpt-5.5@openai",
                    model_name="gpt-5.5",
                    provider="openai",
                    llm_config=first_config,
                ),
                ModelConfigCandidate(
                    selector="gpt-5.4@openrouter",
                    model_name="gpt-5.4",
                    provider="openrouter",
                    llm_config=second_config,
                ),
            ]
        )

        session = Session.create(work_dir=project_dir)
        session.append_history([message.UserMessage(parts=message.text_parts_from_str("try fallback"))])
        session_ctx = SessionContext(
            session_id=session.id,
            work_dir=project_dir,
            get_conversation_history=session.get_llm_history,
            append_history=session.append_history,
            file_tracker=session.file_tracker,
            file_change_summary=session.file_change_summary,
            todo_context=build_todo_context(session),
            run_subtask=None,
            request_user_interaction=None,
        )
        profile = AgentProfile(
            llm_client=fallback_client,
            system_prompt="prompt gpt-5.5",
            tools=[],
            attachments=[],
        )

        def _apply_llm_client_change(llm_client: LLMClientABC) -> AgentProfile:
            return AgentProfile(
                llm_client=llm_client,
                system_prompt=f"prompt {llm_client.model_name}",
                tools=[],
                attachments=[],
            )

        executor = TaskExecutor(
            TaskExecutionContext(
                session=session,
                session_ctx=session_ctx,
                profile=profile,
                tool_registry={},
                sub_agent_state=None,
                apply_llm_client_change=_apply_llm_client_change,
            )
        )

        collected: list[events.Event] = []
        async for event in executor.run(message.UserInputPayload(text="try fallback")):
            collected.append(event)

        fallback_events = [e for e in collected if isinstance(e, events.FallbackModelConfigWarnEvent)]
        assert len(fallback_events) == 1
        assert fallback_events[0].from_provider == "openai"
        assert fallback_events[0].to_provider == "openrouter"
        assert second_client.calls[0].system == "prompt gpt-5.4"
        assert any(isinstance(item, message.FallbackModelConfigWarnEntry) for item in session.conversation_history)
        assert "recovered" in [e.task_result for e in collected if isinstance(e, events.TaskFinishEvent)]
        usage_events = [e for e in collected if isinstance(e, events.UsageEvent)]
        assert len(usage_events) == 1
        assert usage_events[0].usage.total_cost is None
        metadata_events = [e for e in collected if isinstance(e, events.TaskMetadataEvent)]
        assert len(metadata_events) == 1
        assert metadata_events[0].metadata.main_agent.usage is not None
        assert metadata_events[0].metadata.main_agent.usage.total_cost is None

        await session.wait_for_flush()
        replayed = list(Session.load(session.id, work_dir=project_dir).get_history_item())
        assert any(isinstance(event, events.FallbackModelConfigWarnEvent) for event in replayed)

    arun(_test())


def test_stream_error_does_not_trigger_cache_break(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Stream-error turns must not emit UsageEvent: empty usage would otherwise
    show up as a false prompt-cache-break alert (cached tokens dropping to 0)."""
    project_dir = tmp_path / "project"
    project_dir.mkdir()

    # Usage with a real cached-token baseline, mimicking a healthy cached turn.
    cached_usage = Usage(
        input_tokens=60_000,
        cached_tokens=52_000,
        output_tokens=5,
        context_size=60_005,
        context_limit=200_000,
        model_name="fake-model",
        provider="test",
    )

    async def _test() -> None:
        harness = await create_harness(work_dir=project_dir, tools={"echo": MockEchoTool}, monkeypatch=monkeypatch)

        # Turn 1: healthy response establishes cached-token baseline via tool call.
        harness.fake_llm.enqueue(
            message.AssistantMessage(
                parts=[message.ToolCallPart(call_id="call-1", tool_name="echo", arguments_json='{"text": "hi"}')],
                stop_reason="tool_use",
                usage=cached_usage,
            ),
        )
        # Turn 2: LLM client signals a mid-stream network failure. Matches real
        # client behavior: StreamErrorItem + AssistantMessage(stop_reason="error",
        # usage=<empty>). Retry attempt 1 emits the StreamErrorItem again, retry
        # attempt 2 recovers.
        harness.fake_llm.enqueue(
            message.StreamErrorItem(error="RemoteProtocolError peer closed connection"),
            message.AssistantMessage(parts=[], stop_reason="error", usage=Usage()),
        )
        # Turn 2 recovery: same prompt, cache still warm.
        recovered_usage = Usage(
            input_tokens=60_100,
            cached_tokens=52_000,
            output_tokens=5,
            context_size=60_105,
            context_limit=200_000,
            model_name="fake-model",
            provider="test",
        )
        harness.fake_llm.enqueue(
            message.AssistantTextDelta(content="recovered"),
            message.AssistantMessage(
                parts=[message.TextPart(text="recovered")],
                stop_reason="stop",
                usage=recovered_usage,
            ),
        )

        collected = await harness.run_task("try again")

        error_messages = [e.error_message for e in collected if isinstance(e, events.ErrorEvent)]
        # Retry happened.
        assert any("Retrying" in msg for msg in error_messages)
        # But no false cache-break alert despite cached 52,000 -> 0 on the error turn.
        assert not any("cache break" in msg.lower() for msg in error_messages)

        # Error turn's empty usage was not surfaced as a UsageEvent.
        usage_events = [e for e in collected if isinstance(e, events.UsageEvent)]
        assert usage_events, "expected successful turns to still emit UsageEvent"
        for ue in usage_events:
            assert ue.usage.input_tokens > 0 or ue.usage.cached_tokens > 0

    arun(_test())


def test_empty_response_triggers_retry_error_event(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Empty model responses emit a retryable ErrorEvent before retrying."""
    project_dir = tmp_path / "project"
    project_dir.mkdir()

    async def _test() -> None:
        harness = await create_harness(work_dir=project_dir, monkeypatch=monkeypatch)

        harness.fake_llm.enqueue(
            message.AssistantMessage(parts=[], stop_reason="stop", usage=_make_usage()),
        )
        harness.fake_llm.enqueue(
            message.AssistantTextDelta(content="recovered"),
            _text_assistant_message("recovered"),
        )

        collected = await harness.run_task("try again")

        error_events = [e for e in collected if isinstance(e, events.ErrorEvent)]
        assert len(error_events) == 1
        assert error_events[0].can_retry is True
        assert error_events[0].error_message == "Empty response from model, retrying 1/3"

        assert harness.get_user_texts() == [
            "try again",
            EMPTY_RESPONSE_CONTINUATION_PROMPT,
        ]
        assert "[DONE]" not in EMPTY_RESPONSE_CONTINUATION_PROMPT
        assert "recovered" in harness.get_assistant_texts()

    arun(_test())


def test_task_lifecycle_events(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """All lifecycle events are emitted."""
    project_dir = tmp_path / "project"
    project_dir.mkdir()

    async def _test() -> None:
        harness = await create_harness(work_dir=project_dir, monkeypatch=monkeypatch)
        harness.fake_llm.enqueue(
            message.AssistantTextDelta(content="hi"),
            _text_assistant_message("hi"),
        )

        collected = await harness.run_task("hello")

        event_types = {type(e) for e in collected}
        assert events.TaskStartEvent in event_types
        assert events.TurnStartEvent in event_types
        assert events.TurnEndEvent in event_types
        assert events.TaskMetadataEvent in event_types
        assert events.TaskFinishEvent in event_types

    arun(_test())


def test_task_file_change_summary_event_is_task_scoped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    existing_path = str(project_dir / "existing.py")
    created_path = str(project_dir / "created.py")
    deleted_path = str(project_dir / "deleted.py")

    async def _test() -> None:
        harness = await create_harness(work_dir=project_dir, tools={"change": MockChangeTool}, monkeypatch=monkeypatch)
        harness.session.file_change_summary.record_edited(existing_path)
        harness.session.file_change_summary.add_diff(added=10, removed=1, path=existing_path)

        harness.fake_llm.enqueue(
            _tool_call_assistant_message(
                [
                    (
                        "change",
                        "call_1",
                        json.dumps({"path": existing_path, "added": 2, "removed": 3}),
                    ),
                    (
                        "change",
                        "call_2",
                        json.dumps({"path": created_path, "added": 4, "created": True}),
                    ),
                    (
                        "change",
                        "call_3",
                        json.dumps({"path": deleted_path, "removed": 5, "deleted": True}),
                    ),
                ]
            )
        )
        harness.fake_llm.enqueue(
            message.AssistantTextDelta(content="done"),
            _text_assistant_message("done"),
        )

        collected = await harness.run_task("change files")

        summary_events = [e for e in collected if isinstance(e, events.TaskFileChangeSummaryEvent)]
        assert len(summary_events) == 1
        metadata_index = next(i for i, e in enumerate(collected) if isinstance(e, events.TaskMetadataEvent))
        summary_index = next(i for i, e in enumerate(collected) if isinstance(e, events.TaskFileChangeSummaryEvent))
        assert metadata_index < summary_index
        files = {item.path: item for item in summary_events[0].summary.files}
        assert files[existing_path].added == 2
        assert files[existing_path].removed == 3
        assert files[existing_path].created is False
        assert files[existing_path].edited is False
        assert files[created_path].added == 4
        assert files[created_path].removed == 0
        assert files[created_path].created is True
        assert files[deleted_path].added == 0
        assert files[deleted_path].removed == 5
        assert files[deleted_path].deleted is True

        history_summaries = [
            h for h in harness.get_history_messages() if isinstance(h, message.TaskFileChangeSummaryEntry)
        ]
        assert history_summaries == [summary_events[0].summary]
        history = harness.get_history_messages()
        history_metadata_index = next(i for i, h in enumerate(history) if isinstance(h, TaskMetadataItem))
        history_summary_index = next(
            i for i, h in enumerate(history) if isinstance(h, message.TaskFileChangeSummaryEntry)
        )
        assert history_metadata_index < history_summary_index

        await harness.session.wait_for_flush()
        replayed = list(Session.load(harness.session.id, work_dir=project_dir).get_history_item())
        assert any(isinstance(event, events.TaskFileChangeSummaryEvent) for event in replayed)
        replayed_metadata_index = next(i for i, e in enumerate(replayed) if isinstance(e, events.TaskMetadataEvent))
        replayed_summary_index = next(
            i for i, e in enumerate(replayed) if isinstance(e, events.TaskFileChangeSummaryEvent)
        )
        assert replayed_metadata_index < replayed_summary_index

    arun(_test())


def test_task_file_change_summary_uses_git_diff_for_external_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=project_dir, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=project_dir, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=project_dir, check=True)

    existing_path = project_dir / "existing.py"
    existing_path.write_text("one\n", encoding="utf-8")
    gitignore_path = project_dir / ".gitignore"
    gitignore_path.write_text("ignored.txt\n", encoding="utf-8")
    subprocess.run(["git", "add", "existing.py", ".gitignore"], cwd=project_dir, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=project_dir, check=True)

    preexisting_path = project_dir / "preexisting.py"
    preexisting_path.write_text("already here\n", encoding="utf-8")
    created_path = project_dir / "created.py"
    ignored_path = project_dir / "ignored.txt"

    async def _test() -> None:
        harness = await create_harness(
            work_dir=project_dir,
            tools={"fs_change": MockFilesystemChangeTool},
            monkeypatch=monkeypatch,
        )
        harness.fake_llm.enqueue(
            _tool_call_assistant_message(
                [
                    (
                        "fs_change",
                        "call_1",
                        json.dumps({"path": str(existing_path), "content": "one\ntwo\n"}),
                    ),
                    (
                        "fs_change",
                        "call_2",
                        json.dumps({"path": str(created_path), "content": "created\n"}),
                    ),
                    (
                        "fs_change",
                        "call_3",
                        json.dumps({"path": str(ignored_path), "content": "ignored\n", "record": True}),
                    ),
                ]
            )
        )
        harness.fake_llm.enqueue(
            message.AssistantTextDelta(content="done"),
            _text_assistant_message("done"),
        )

        collected = await harness.run_task("change files")

        summary_events = [e for e in collected if isinstance(e, events.TaskFileChangeSummaryEvent)]
        assert len(summary_events) == 1
        files = {Path(item.path): item for item in summary_events[0].summary.files}
        assert set(files) == {existing_path, created_path, ignored_path}
        assert files[existing_path].added == 1
        assert files[existing_path].removed == 0
        assert files[existing_path].edited is True
        assert files[created_path].added == 1
        assert files[created_path].removed == 0
        assert files[created_path].created is True
        assert files[ignored_path].added == 1
        assert files[ignored_path].removed == 0
        assert files[ignored_path].created is True
        assert preexisting_path not in files

        assert harness.session.file_change_summary.edited_files == [str(existing_path)]
        assert set(harness.session.file_change_summary.created_files) == {str(created_path), str(ignored_path)}
        assert harness.session.file_change_summary.diff_lines_added == 3
        assert harness.session.file_change_summary.diff_lines_removed == 0

    arun(_test())


def test_llm_receives_correct_context(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """LLM call receives user message and tool schemas in params."""
    project_dir = tmp_path / "project"
    project_dir.mkdir()

    async def _test() -> None:
        harness = await create_harness(
            work_dir=project_dir,
            tools={"echo": MockEchoTool},
            monkeypatch=monkeypatch,
        )

        captured_params: list[llm_param.LLMCallParameter] = []

        def _capture(param: llm_param.LLMCallParameter) -> list[message.LLMStreamItem]:
            captured_params.append(param)
            return [
                message.AssistantTextDelta(content="ok"),
                _text_assistant_message("ok"),
            ]

        harness.fake_llm.enqueue_factory(_capture)

        await harness.run_task("check context")

        assert len(captured_params) == 1
        param = captured_params[0]
        # User message present in input
        user_msgs = [m for m in param.input if isinstance(m, message.UserMessage)]
        assert len(user_msgs) == 1
        assert message.join_text_parts(user_msgs[0].parts) == "check context"
        # Tool schemas passed
        assert param.tools is not None
        tool_names = {t.name for t in param.tools}
        assert "echo" in tool_names

    arun(_test())


def test_multi_turn_tool_loop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Two consecutive tool calls before final text (3 turns total)."""
    project_dir = tmp_path / "project"
    project_dir.mkdir()

    async def _test() -> None:
        harness = await create_harness(
            work_dir=project_dir,
            tools={"echo": MockEchoTool},
            monkeypatch=monkeypatch,
        )

        # Turn 1: tool call
        harness.fake_llm.enqueue(
            _tool_call_assistant_message([("echo", "call_1", '{"text":"step1"}')]),
        )
        # Turn 2: another tool call
        harness.fake_llm.enqueue(
            _tool_call_assistant_message([("echo", "call_2", '{"text":"step2"}')]),
        )
        # Turn 3: final text
        harness.fake_llm.enqueue(
            message.AssistantTextDelta(content="finished"),
            _text_assistant_message("finished"),
        )

        collected = await harness.run_task("multi step")

        # 3 turns
        turn_starts = [e for e in collected if isinstance(e, events.TurnStartEvent)]
        turn_ends = [e for e in collected if isinstance(e, events.TurnEndEvent)]
        assert len(turn_starts) == 3
        assert len(turn_ends) == 3

        # Full history sequence
        history = harness.get_history_messages()
        msg_types = [
            type(h).__name__
            for h in history
            if isinstance(h, (message.UserMessage, message.AssistantMessage, message.ToolResultMessage))
        ]
        assert msg_types == [
            "UserMessage",
            "AssistantMessage",  # tool call 1
            "ToolResultMessage",
            "AssistantMessage",  # tool call 2
            "ToolResultMessage",
            "AssistantMessage",  # final text
        ]

        # Both tool calls executed
        assert MockEchoTool.calls == ["step1", "step2"]

    arun(_test())
