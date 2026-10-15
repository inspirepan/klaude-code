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
from klaude_code.agent.agent import Agent
from klaude_code.agent.agent_profile import AgentProfile
from klaude_code.agent.attachments.files import at_file_reader_attachment, file_changed_externally_attachment
from klaude_code.agent.attachments.skills import skill_attachment
from klaude_code.agent.compaction import CompactionResult
from klaude_code.agent.runtime.llm import FallbackLLMClient
from klaude_code.agent.task import SessionContext, TaskExecutionContext, TaskExecutor
from klaude_code.config.config import Config, ModelConfigCandidate
from klaude_code.llm.client import LLMClientABC, LLMStreamABC
from klaude_code.llm.openai_compatible.client import build_payload
from klaude_code.llm.usage import MetadataTracker, error_stream_items
from klaude_code.protocol import events, llm_param, message
from klaude_code.protocol.models import AtFileOpsUIItem, ExternalFileChangesUIItem, TaskMetadataItem, Usage
from klaude_code.session import store as session_store
from klaude_code.session.codec import encode_jsonl_line
from klaude_code.session.session import Session
from klaude_code.skill.loader import Skill
from klaude_code.tool.core.abc import ToolABC
from klaude_code.tool.core.context import ToolContext, build_todo_context
from tests.agent.agent_harness import ScriptedLLMStream, create_harness


@pytest.mark.parametrize("with_tools", [False, True])
def test_steering_batches_fifo_after_complete_step(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, with_tools: bool
) -> None:
    async def _test() -> None:
        harness = await create_harness(work_dir=tmp_path, monkeypatch=monkeypatch)
        profile = AgentProfile(
            llm_client=harness.fake_llm,
            system_prompt="test",
            attachments=[],
            tools=[MockEchoTool.schema()] if with_tools else [],
        )
        monkeypatch.setattr("klaude_code.agent.agent.get_registry", lambda: {"echo": MockEchoTool})
        agent = Agent(harness.session, profile)
        harness.session.append_history([message.UserMessage(parts=message.text_parts_from_str("initial"))])
        queued_ids: list[str] = []

        def first_request(param: llm_param.LLMCallParameter) -> list[message.LLMStreamItem]:
            assert [
                message.join_text_parts(item.parts) for item in param.input if isinstance(item, message.UserMessage)
            ] == ["initial"]
            agent.follow_up(message.UserInputPayload(text="first", source="user"))
            agent.follow_up(message.UserInputPayload(text="second"))
            queued_ids.extend(item.id for item in harness.session.follow_up_queue)
            if with_tools:
                return [_tool_call_assistant_message([("echo", "a", '{"text":"a"}'), ("echo", "b", '{"text":"b"}')])]
            return [_text_assistant_message("original final")]

        def next_request(param: llm_param.LLMCallParameter) -> list[message.LLMStreamItem]:
            users = [item for item in param.input if isinstance(item, message.UserMessage)]
            assert [message.join_text_parts(item.parts) for item in users] == ["initial", "first", "second"]
            assert [item.id for item in users[1:]] == queued_ids
            assert users[1].source == "user"
            if with_tools:
                results = [item for item in param.input if isinstance(item, message.ToolResultMessage)]
                assert {item.call_id for item in results} == {"a", "b"}
                assert all(param.input.index(item) < param.input.index(users[1]) for item in results)
            return [_text_assistant_message("steered final")]

        harness.fake_llm.enqueue_factory(first_request)
        harness.fake_llm.enqueue_factory(next_request)
        collected = [event async for event in agent.run_task(message.UserInputPayload(text="initial"))]
        assert [event.content for event in collected if isinstance(event, events.UserMessageEvent)] == [
            "first",
            "second",
        ]
        assert len([event for event in collected if isinstance(event, events.TaskStartEvent)]) == 1
        finishes = [event for event in collected if isinstance(event, events.TaskFinishEvent)]
        assert len(finishes) == 1 and finishes[0].task_result == "steered final"
        assert not agent.pending_input_activity.is_set()
        assert Session.load(harness.session.id, tmp_path).follow_up_queue == []

    arun(_test())


@pytest.mark.parametrize("cancel", [False, True])
@pytest.mark.parametrize("restart", [False, True])
def test_steering_history_flush_precedes_ack_and_restore_deduplicates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cancel: bool, restart: bool
) -> None:
    async def _test() -> None:
        from PIL import Image

        harness = await create_harness(work_dir=tmp_path, monkeypatch=monkeypatch)
        profile = AgentProfile(llm_client=harness.fake_llm, system_prompt="test", tools=[], attachments=[])
        agent = Agent(harness.session, profile)
        image_path = tmp_path / "input.png"
        Image.new("RGB", (2, 2), color="red").save(image_path)
        agent.follow_up(
            message.UserInputPayload(
                text="image", source="user", images=[message.ImageFilePart(file_path=str(image_path))]
            )
        )
        agent.follow_up(message.UserInputPayload(text="second"))
        ids = [item.id for item in harness.session.follow_up_queue]
        flushed = asyncio.Event()
        release = asyncio.Event()
        original_flush = Session.wait_for_flush

        async def block_ack(session: Session) -> None:
            await original_flush(session)
            flushed.set()
            await release.wait()
            if not cancel:
                raise OSError("ack window crash")

        monkeypatch.setattr(Session, "wait_for_flush", block_ack)

        async def inject() -> list[events.Event]:
            return [event async for event in agent.inject_pending_inputs()]

        task = asyncio.create_task(inject())
        await asyncio.wait_for(flushed.wait(), timeout=5)
        assert [item.id for item in Session.load_meta(harness.session.id, tmp_path).follow_up_queue] == ids
        assert [item.text for item in agent.follow_up_snapshot()] == ["image", "second"]
        # New enqueue and withdrawal must not delete the admitting batch.
        agent.follow_up(message.UserInputPayload(text="withdraw me"))
        assert [item.text for item in agent.pop_all_follow_up()] == ["withdraw me"]
        assert [item.id for item in Session.load_meta(harness.session.id, tmp_path).follow_up_queue] == ids
        if cancel:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            release.set()
            with pytest.raises(OSError, match="ack window crash"):
                await task
        release.set()
        await asyncio.sleep(0)
        monkeypatch.setattr(Session, "wait_for_flush", original_flush)
        restored_session = Session.load(harness.session.id, tmp_path) if restart else harness.session
        restored = Agent(restored_session, profile) if restart else agent
        restored.follow_up(message.UserInputPayload(text="after restart"))
        emitted = [event async for event in restored.inject_pending_inputs()]
        assert [event.content for event in emitted if isinstance(event, events.UserMessageEvent)] == (
            ["after restart"] if restart else ["image", "second", "after restart"]
        )
        users = [
            item
            for item in Session.load(harness.session.id, tmp_path).conversation_history
            if isinstance(item, message.UserMessage)
        ]
        assert [item.id for item in users[:2]] == ids
        assert len(users) == 3
        frozen = next(part for part in users[0].parts if isinstance(part, message.ImageFilePart))
        assert frozen.frozen and frozen.file_path != str(image_path)
        assert Path(frozen.file_path).read_bytes() == image_path.read_bytes()
        assert users[0].source == "user"
        assert restored_session.follow_up_queue == []

    arun(_test())


@pytest.mark.parametrize("operation", ["fresh_enqueue", "enqueue", "withdraw", "admit"])
def test_operator_queue_metadata_failure_rolls_back_and_retries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    async def _test() -> None:
        harness = await create_harness(work_dir=tmp_path, monkeypatch=monkeypatch)
        agent = Agent(
            harness.session, AgentProfile(llm_client=harness.fake_llm, system_prompt="test", tools=[], attachments=[])
        )
        if operation != "fresh_enqueue":
            agent.follow_up(message.UserInputPayload(text="original"))
        before = agent.follow_up_records()
        original = session_store._write_json_dict_atomic
        failed = True

        def write(path: Path, data: dict[str, Any], suffix: str) -> None:
            if failed and suffix in {"u", "c"}:
                raise OSError("queue metadata failure")
            original(path, data, suffix)

        monkeypatch.setattr(session_store, "_write_json_dict_atomic", write)

        async def change() -> None:
            if operation in {"fresh_enqueue", "enqueue"}:
                agent.follow_up(message.UserInputPayload(text="new"))
            elif operation == "withdraw":
                agent.pop_all_follow_up()
            else:
                async for _ in agent.inject_pending_inputs():
                    pass

        for _ in range(2):
            with pytest.raises(OSError):
                await change()
            assert agent.follow_up_records() == before
            assert agent.session.follow_up_queue == list(before)
            assert agent.pending_input_activity.is_set() == bool(before)
            assert Session.load_meta(agent.session.id, tmp_path).follow_up_queue == list(before)
        failed = False
        await change()
        expected = ["new"] if operation == "fresh_enqueue" else ["original", "new"] if operation == "enqueue" else []
        assert [item.text for item in agent.follow_up_snapshot()] == expected
        assert [item.input.text for item in Session.load_meta(agent.session.id, tmp_path).follow_up_queue] == expected
        if operation == "admit":
            loaded = Session.load(agent.session.id, tmp_path)
            assert sum(isinstance(item, message.UserMessage) for item in loaded.conversation_history) == 1

    arun(_test())


@pytest.mark.parametrize("failure", ["before", "prefix", "tail", "meta"])
@pytest.mark.parametrize("restart", [False, True])
@pytest.mark.parametrize("interleave", [False, True])
def test_steering_writer_failure_retains_batch_and_retry_reaches_disk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str, restart: bool, interleave: bool
) -> None:
    async def _test() -> None:
        harness = await create_harness(work_dir=tmp_path, monkeypatch=monkeypatch)
        agent = Agent(
            harness.session,
            AgentProfile(llm_client=harness.fake_llm, system_prompt="test", tools=[], attachments=[]),
        )
        agent.follow_up(message.UserInputPayload(text="first"))
        agent.follow_up(message.UserInputPayload(text="second"))
        ids = [item.id for item in harness.session.follow_up_queue]
        original_write = session_store.JsonlSessionWriter._write_batch_sync
        original_meta_write = session_store._write_json_dict_atomic  # pyright: ignore[reportPrivateUsage]
        batches: list[list[str | None]] = []

        def failing_meta_write(path: Path, data: dict[str, Any], suffix: str) -> None:
            if failure == "meta" and suffix == "w" and len(batches) == 1:
                raise OSError("writer failed")
            original_meta_write(path, data, suffix)

        def failing_write(writer: session_store.JsonlSessionWriter, batch: Any) -> None:
            batches.append([item.id for item in batch.items])
            if len(batches) != 1:
                original_write(writer, batch)
                return
            if failure in ("prefix", "tail"):
                path = Session.paths(tmp_path).events_file(harness.session.id)
                data = encode_jsonl_line(batch.items[0]).encode()
                if failure == "tail":
                    data += encode_jsonl_line(batch.items[1]).encode()[:30]
                path.write_bytes(data)
            elif failure == "meta":
                original_write(writer, batch)
            raise OSError("writer failed")

        monkeypatch.setattr(session_store.JsonlSessionWriter, "_write_batch_sync", failing_write)
        monkeypatch.setattr(session_store, "_write_json_dict_atomic", failing_meta_write)
        with pytest.raises(OSError, match="writer failed"):
            _ = [event async for event in agent.inject_pending_inputs()]
        assert batches == [ids]
        assert [item.text for item in agent.follow_up_snapshot()] == ["first", "second"]
        assert agent.pending_input_activity.is_set()
        assert [item.id for item in Session.load_meta(harness.session.id, tmp_path).follow_up_queue] == ids

        if restart:
            agent = Agent(Session.load(harness.session.id, tmp_path), agent.profile)
        fresh = message.UserMessage(id="ordinary-input", parts=message.text_parts_from_str("ordinary new input"))
        if interleave:
            # run_agent appends ordinary input before the pending batch retries.
            agent.session.append_history([fresh])
        emitted = [event async for event in agent.inject_pending_inputs()]
        assert batches == ([ids, [fresh.id], ids] if interleave else [ids, ids])
        expected_echoes = ["first", "second"]
        if restart and failure != "before":
            expected_echoes = [] if failure == "meta" else ["second"]
        assert [event.content for event in emitted if isinstance(event, events.UserMessageEvent)] == expected_echoes
        loaded = Session.load(harness.session.id, tmp_path)
        prefix_count = {"before": 0, "prefix": 1, "tail": 1, "meta": 2}[failure]
        disk_ids: list[str | None] = [*ids[:prefix_count], fresh.id, *ids[prefix_count:]] if interleave else [*ids]
        assert [item.id for item in loaded.conversation_history if isinstance(item, message.UserMessage)] == disk_ids
        users = [item for item in agent.session.conversation_history if isinstance(item, message.UserMessage)]
        assert {item.id for item in users} == set(disk_ids)
        assert [
            message.join_text_parts(item.parts)
            for item in loaded.conversation_history
            if isinstance(item, message.UserMessage)
        ] == [{ids[0]: "first", ids[1]: "second", fresh.id: "ordinary new input"}[item_id] for item_id in disk_ids]
        assert loaded.follow_up_queue == []
        assert not agent.pending_input_activity.is_set()
        assert Session.paths(tmp_path).events_file(loaded.id).read_text().count("\n") == len(disk_ids)
        assert [agent.session.line_index_of(i) for i in range(len(users))] == [
            disk_ids.index(item.id) for item in users
        ]
        agent.session.append_history([message.DeveloperMessage(parts=[])])
        await agent.session.wait_for_flush()
        assert agent.session.line_index_of(len(users)) == len(disk_ids)

    arun(_test())


@pytest.mark.parametrize("persisted_count", [1, 2])
def test_restored_admission_loads_all_references_without_scanning_stale_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, persisted_count: int
) -> None:
    async def _test() -> None:
        harness = await create_harness(work_dir=tmp_path, monkeypatch=monkeypatch)
        (tmp_path / "recent.txt").write_text("RECENT_FILE_CONTENT")
        (tmp_path / "stale.txt").write_text("STALE_FILE_CONTENT")
        skill_path = tmp_path / "SKILL.md"
        skill_path.write_text("RECENT_SKILL_CONTENT")
        skill = Skill(name="recent", description="test", location="project", skill_path=skill_path, base_dir=tmp_path)
        resolved: list[str] = []

        def resolve(_: Session, name: str) -> Skill:
            resolved.append(name)
            return skill

        monkeypatch.setattr("klaude_code.agent.attachments.skills.resolve_skill_for_input", resolve)
        profile = AgentProfile(
            llm_client=harness.fake_llm,
            system_prompt="test",
            tools=[],
            attachments=[at_file_reader_attachment, skill_attachment],
        )
        harness.session.append_history(
            [message.UserMessage(parts=message.text_parts_from_str("@stale.txt /skill:stale"))]
        )
        await harness.session.wait_for_flush()
        agent = Agent(harness.session, profile)
        agent.follow_up(message.UserInputPayload(text="@recent.txt /skill:recent"))
        agent.follow_up(message.UserInputPayload(text="last without references"))
        queued = harness.session.follow_up_queue
        # Simulate a crash after history reached disk but before queue ack.
        harness.session.append_history(
            [
                message.UserMessage(id=item.id, parts=message.text_parts_from_str(item.input.text))
                for item in queued[:persisted_count]
            ],
            deduplicate_user_inputs=True,
        )
        await harness.session.wait_for_flush()
        restored = Agent(Session.load(harness.session.id, tmp_path), profile)

        def request(param: llm_param.LLMCallParameter) -> list[message.LLMStreamItem]:
            content = "\n".join(
                message.join_text_parts(item.parts)
                for item in param.input
                if isinstance(item, message.DeveloperMessage)
            )
            assert content.count("RECENT_FILE_CONTENT") == 1
            assert content.count("RECENT_SKILL_CONTENT") == 1
            assert "stale" not in content
            assert resolved == ["recent"]
            return [_text_assistant_message("done")]

        harness.fake_llm.enqueue_factory(request)
        collected = [event async for event in restored.run_task(message.UserInputPayload(text=""))]
        assert any(isinstance(event, events.TaskFinishEvent) and event.task_result == "done" for event in collected)
        assert [
            item.id
            for item in Session.load(harness.session.id, tmp_path).conversation_history
            if isinstance(item, message.UserMessage)
        ][1:] == [item.id for item in queued]

    arun(_test())


def test_repeated_external_file_transitions_reach_each_request(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _test() -> None:
        harness = await create_harness(work_dir=tmp_path, monkeypatch=monkeypatch)
        file_path = tmp_path / "state.txt"
        file_path.write_text("A\n")
        agent = Agent(
            harness.session,
            AgentProfile(
                llm_client=harness.fake_llm,
                system_prompt="test",
                tools=[],
                attachments=[at_file_reader_attachment, file_changed_externally_attachment],
            ),
        )
        harness.session.append_history([message.UserMessage(parts=message.text_parts_from_str("@state.txt"))])
        transitions: list[str] = []
        request_count = 0

        def request(param: llm_param.LLMCallParameter) -> list[message.LLMStreamItem]:
            nonlocal request_count
            changes = [
                item
                for item in param.input
                if isinstance(item, message.DeveloperMessage)
                and item.ui_extra is not None
                and any(isinstance(extra, ExternalFileChangesUIItem) for extra in item.ui_extra.items)
            ]
            assert len(changes) == request_count
            if changes:
                transitions.append(message.join_text_parts(changes[-1].parts))
                assert f"+\t{'B' if request_count % 2 else 'A'}" in transitions[-1]
            assert harness.session.file_tracker[str(file_path)].cached_content == (
                "B\n" if request_count % 2 else "A\n"
            )
            request_count += 1
            if request_count < 4:
                file_path.write_text("B\n" if request_count % 2 else "A\n")
                agent.follow_up(message.UserInputPayload(text="continue"))
            return [_text_assistant_message("done")]

        for _ in range(4):
            harness.fake_llm.enqueue_factory(request)
        collected = [event async for event in agent.run_task(message.UserInputPayload(text="@state.txt"))]
        assert request_count == 4
        assert transitions[0] == transitions[2]
        assert len([event for event in collected if isinstance(event, events.DeveloperMessageEvent)]) == 4

    arun(_test())


@pytest.mark.parametrize("boundary", ["first", "threshold", "overflow", "retry", "complete"])
def test_steering_is_checked_before_first_compacted_and_retried_requests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, boundary: str
) -> None:
    async def _test() -> None:
        harness = await create_harness(work_dir=tmp_path, monkeypatch=monkeypatch)
        file_path = tmp_path / "steering.txt"
        file_path.write_text("STEERING_FILE_CONTENT")
        (tmp_path / "stale.txt").write_text("STALE_FILE_CONTENT")
        skill_path = tmp_path / "SKILL.md"
        skill_path.write_text("STEERING_SKILL_CONTENT")
        skill = Skill(name="steer", description="test", location="project", skill_path=skill_path, base_dir=tmp_path)
        resolved: list[str] = []

        def resolve(_: Session, name: str) -> Skill:
            resolved.append(name)
            return skill

        monkeypatch.setattr("klaude_code.agent.attachments.skills.resolve_skill_for_input", resolve)
        profile = AgentProfile(
            llm_client=harness.fake_llm,
            system_prompt="test",
            tools=[],
            attachments=[at_file_reader_attachment, skill_attachment],
        )
        agent = Agent(harness.session, profile)
        harness.session.append_history(
            [
                message.UserMessage(parts=message.text_parts_from_str("old @stale.txt /skill:stale")),
                message.UserMessage(parts=message.text_parts_from_str("initial")),
            ]
        )

        batch_queued = False

        def enqueue_batch() -> None:
            nonlocal batch_queued
            if batch_queued:
                return
            batch_queued = True
            agent.follow_up(message.UserInputPayload(text="pending @steering.txt /skill:steer"))
            agent.follow_up(message.UserInputPayload(text="duplicate @./steering.txt /skill:steer"))
            agent.follow_up(message.UserInputPayload(text="last message without references"))

        if boundary == "first":
            enqueue_batch()
        elif boundary == "threshold":
            monkeypatch.setattr(task_module, "should_compact_threshold", lambda **_: True)

        async def compact(**_: Any) -> CompactionResult:
            enqueue_batch()
            return CompactionResult(
                summary="summary", first_kept_index=0, tokens_before=100, details=None, kept_items_brief=[]
            )

        monkeypatch.setattr(task_module, "run_compaction", compact)
        monkeypatch.setattr(task_module, "_retry_delay_seconds", lambda _: 0)
        if boundary in ("overflow", "retry"):
            harness.fake_llm.enqueue(
                message.StreamErrorItem(
                    error="maximum context length exceeded" if boundary == "overflow" else "temporary failure"
                )
            )
        elif boundary == "complete":

            def complete_request(_: llm_param.LLMCallParameter) -> list[message.LLMStreamItem]:
                enqueue_batch()
                return [_text_assistant_message("original final")]

            harness.fake_llm.enqueue_factory(complete_request)

        admitted_requests = 0

        def request(param: llm_param.LLMCallParameter) -> list[message.LLMStreamItem]:
            nonlocal admitted_requests
            admitted_requests += 1
            assert any(
                isinstance(item, message.UserMessage) and message.join_text_parts(item.parts).startswith("pending")
                for item in param.input
            )
            attachments = [item for item in param.input if isinstance(item, message.DeveloperMessage)]
            content = "\n".join(message.join_text_parts(item.parts) for item in attachments)
            assert content.count("STEERING_FILE_CONTENT") == 1
            assert content.count("STEERING_SKILL_CONTENT") == 1
            assert "stale.txt" not in content
            file_ops = [
                op
                for item in attachments
                if item.ui_extra is not None
                for ui_item in item.ui_extra.items
                if isinstance(ui_item, AtFileOpsUIItem)
                for op in ui_item.ops
            ]
            assert [op.path for op in file_ops] == [str(file_path.resolve())]
            assert resolved == ["steer"]
            if admitted_requests == 1:
                return [message.StreamErrorItem(error="temporary failure after admission")]
            return [_text_assistant_message("done")]

        harness.fake_llm.enqueue_factory(request)
        harness.fake_llm.enqueue_factory(request)
        collected: list[events.Event] = []
        async for event in agent.run_task(message.UserInputPayload(text="initial")):
            collected.append(event)
            if boundary == "retry" and isinstance(event, events.ErrorEvent) and event.can_retry:
                enqueue_batch()
        assert len([event for event in collected if isinstance(event, events.UserMessageEvent)]) == 3
        assert admitted_requests == 2
        assert any(isinstance(event, events.TaskFinishEvent) and event.task_result == "done" for event in collected)

    arun(_test())


def test_steering_reloads_recent_batch_references_after_compaction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _test() -> None:
        harness = await create_harness(work_dir=tmp_path, monkeypatch=monkeypatch)
        (tmp_path / "recent.txt").write_text("RECENT_FILE_CONTENT")
        (tmp_path / "stale.txt").write_text("STALE_FILE_CONTENT")
        skill_path = tmp_path / "SKILL.md"
        skill_path.write_text("RECENT_SKILL_CONTENT")
        skill = Skill(name="recent", description="test", location="project", skill_path=skill_path, base_dir=tmp_path)
        resolved: list[str] = []

        def resolve(_: Session, name: str) -> Skill:
            resolved.append(name)
            return skill

        monkeypatch.setattr("klaude_code.agent.attachments.skills.resolve_skill_for_input", resolve)
        profile = AgentProfile(
            llm_client=harness.fake_llm,
            system_prompt="test",
            tools=[],
            attachments=[at_file_reader_attachment, skill_attachment],
        )
        agent = Agent(harness.session, profile)
        harness.session.append_history(
            [
                message.UserMessage(parts=message.text_parts_from_str("@stale.txt /skill:stale")),
                message.UserMessage(parts=message.text_parts_from_str("initial")),
            ]
        )
        agent.follow_up(message.UserInputPayload(text="@recent.txt /skill:recent"))
        agent.follow_up(message.UserInputPayload(text="last without references"))

        async def compact(**_: Any) -> CompactionResult:
            # Drop the user messages and attachments: only the recent admission
            # batch, not a history-wide scan, can restore these references.
            return CompactionResult(
                summary="summary",
                first_kept_index=len(harness.session.conversation_history),
                tokens_before=100,
                details=None,
                kept_items_brief=[],
            )

        monkeypatch.setattr(task_module, "run_compaction", compact)

        def request(param: llm_param.LLMCallParameter) -> list[message.LLMStreamItem]:
            content = "\n".join(
                message.join_text_parts(item.parts)
                for item in param.input
                if isinstance(item, message.DeveloperMessage)
            )
            assert content.count("RECENT_FILE_CONTENT") == 1
            assert content.count("RECENT_SKILL_CONTENT") == 1
            assert "stale" not in content
            if len(resolved) == 1:
                return [message.StreamErrorItem(error="maximum context length exceeded")]
            assert resolved == ["recent", "recent"]
            return [_text_assistant_message("done")]

        harness.fake_llm.enqueue_factory(request)
        harness.fake_llm.enqueue_factory(request)
        collected = [event async for event in agent.run_task(message.UserInputPayload(text="initial"))]
        assert any(isinstance(event, events.TaskFinishEvent) and event.task_result == "done" for event in collected)
        assert resolved == ["recent", "recent"]

    arun(_test())


def arun[T](coro: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _isolate_home(isolated_home: Path) -> Path:  # pyright: ignore[reportUnusedFunction]
    return isolated_home


@pytest.fixture(autouse=True)
def _hermetic_provider_config(monkeypatch: pytest.MonkeyPatch) -> None:  # pyright: ignore[reportUnusedFunction]
    # FallbackLLMClient.call() consults load_config() for provider disable
    # toggles; the developer's real ~/.klaude config must not leak in.
    monkeypatch.setattr(runtime_llm, "load_config", lambda: Config(provider_list=[]))


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
    """Tool call step -> follow-up text response."""
    project_dir = tmp_path / "project"
    project_dir.mkdir()

    async def _test() -> None:
        harness = await create_harness(
            work_dir=project_dir,
            tools={"echo": MockEchoTool},
            monkeypatch=monkeypatch,
        )

        # Step 1: tool call
        harness.fake_llm.enqueue(
            _tool_call_assistant_message([("echo", "call_1", '{"text":"hello"}')]),
        )
        # Step 2: text response
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

        # Two StepStartEvent and two StepEndEvent
        step_starts = [e for e in collected if isinstance(e, events.StepStartEvent)]
        step_ends = [e for e in collected if isinstance(e, events.StepEndEvent)]
        assert len(step_starts) == 2
        assert len(step_ends) == 2

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

        # Step 1: two tool calls
        harness.fake_llm.enqueue(
            _tool_call_assistant_message(
                [
                    ("echo", "call_1", '{"text":"foo"}'),
                    ("upper", "call_2", '{"text":"bar"}'),
                ]
            ),
        )
        # Step 2: text response
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

        # Step 1: stream error
        harness.fake_llm.enqueue(
            message.StreamErrorItem(error="network error"),
        )
        # Step 2: recovered
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


def test_invalid_assistant_message_error_does_not_retry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    error = (
        "BadRequestError Error code: 400 - {'error': {'type': 'invalid_request_error', "
        "'message': 'Error from provider (Console Go): Upstream request failed: [invalid_request_error] "
        "Invalid assistant message: content or tool_calls must be set'}}"
    )

    async def _test() -> None:
        harness = await create_harness(work_dir=project_dir, monkeypatch=monkeypatch)
        harness.fake_llm.enqueue(message.StreamErrorItem(error=error))
        harness.fake_llm.enqueue(_text_assistant_message("should not retry"))

        collected = await harness.run_task("continue")

        error_events = [event for event in collected if isinstance(event, events.ErrorEvent)]
        assert len(error_events) == 1
        assert error_events[0].can_retry is False
        assert error_events[0].error_message == error
        assert harness.fake_llm.pending_count == 1

    arun(_test())


def test_stream_error_retry_includes_previous_tool_step_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Retry after a stream error sees prior assistant tool call and tool result."""
    project_dir = tmp_path / "project"
    project_dir.mkdir()

    def has_previous_tool_step(items: list[message.HistoryEvent]) -> bool:
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

        # Step 1: successful tool call writes AssistantMessage + ToolResultMessage.
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

        # Step 2 fails once, then the failed step is retried.
        harness.fake_llm.enqueue_factory(stream_error)
        harness.fake_llm.enqueue_factory(recover)

        await harness.run_task("run echo then recover")

        assert len(captured_inputs) == 2
        assert has_previous_tool_step(captured_inputs[0])
        assert has_previous_tool_step(captured_inputs[1])
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


def test_threshold_compaction_uses_compact_model_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project_dir = tmp_path / "project"
    project_dir.mkdir()

    def _always_compact(*, session: Session, config: Any, llm_config: Any) -> bool:
        del session, config, llm_config
        return True

    monkeypatch.setattr(task_module, "should_compact_threshold", _always_compact)

    compaction_model_ids: list[str] = []

    async def _run_compaction(**kwargs: Any) -> CompactionResult:
        llm_config = kwargs["llm_config"]
        assert isinstance(llm_config, llm_param.LLMConfigParameter)
        compaction_model_ids.append(llm_config.model_id)
        if len(compaction_model_ids) == 1:
            raise RuntimeError("model_not_available: compact provider is unavailable")
        return CompactionResult(
            summary="compacted summary",
            first_kept_index=1,
            tokens_before=123,
            details=None,
            kept_items_brief=[],
        )

    monkeypatch.setattr(task_module, "run_compaction", _run_compaction)

    async def _test() -> None:
        main_config = llm_param.LLMConfigParameter(
            provider_name="main",
            protocol=llm_param.LLMClientProtocol.OPENAI,
            model_id="main-model",
        )
        first_compact_config = llm_param.LLMConfigParameter(
            provider_name="openai",
            protocol=llm_param.LLMClientProtocol.OPENAI,
            model_id="compact-first",
        )
        second_compact_config = llm_param.LLMConfigParameter(
            provider_name="openrouter",
            protocol=llm_param.LLMClientProtocol.OPENAI,
            model_id="compact-second",
        )
        main_client = ConfiguredScriptedClient(
            main_config,
            [[message.AssistantTextDelta(content="done"), _text_assistant_message("done")]],
        )
        compact_client = FallbackLLMClient(
            [
                ModelConfigCandidate(
                    selector="compact@openai",
                    model_name="compact",
                    provider="openai",
                    llm_config=first_compact_config,
                ),
                ModelConfigCandidate(
                    selector="compact@openrouter",
                    model_name="compact",
                    provider="openrouter",
                    llm_config=second_compact_config,
                ),
            ]
        )

        session = Session.create(work_dir=project_dir)
        session.append_history([message.UserMessage(parts=message.text_parts_from_str("needs compaction"))])
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
            llm_client=main_client,
            system_prompt="main prompt",
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
                compact_llm_client=compact_client,
            )
        )

        collected: list[events.Event] = []
        async for event in executor.run(message.UserInputPayload(text="needs compaction")):
            collected.append(event)

        assert compaction_model_ids == ["compact-first", "compact-second"]
        fallback_events = [e for e in collected if isinstance(e, events.FallbackModelConfigWarnEvent)]
        assert len(fallback_events) == 1
        assert fallback_events[0].from_provider == "openai"
        assert fallback_events[0].to_provider == "openrouter"
        assert any(isinstance(item, message.CompactionEntry) for item in session.conversation_history)
        assert any(isinstance(item, message.FallbackModelConfigWarnEntry) for item in session.conversation_history)
        assert "done" in [e.task_result for e in collected if isinstance(e, events.TaskFinishEvent)]

    arun(_test())


def test_fork_compaction_falls_back_inherited_main_model(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project_dir = tmp_path / "project"
    project_dir.mkdir()

    def _always_compact(*, session: Session, config: Any, llm_config: Any) -> bool:
        del session, config, llm_config
        return True

    monkeypatch.setattr(task_module, "should_compact_threshold", _always_compact)

    async def _test() -> None:
        first_config = llm_param.LLMConfigParameter(
            provider_name="openai",
            protocol=llm_param.LLMClientProtocol.OPENAI,
            model_id="gpt-5.5",
            context_limit=20_000,
        )
        second_config = llm_param.LLMConfigParameter(
            provider_name="openrouter",
            protocol=llm_param.LLMClientProtocol.OPENAI,
            model_id="gpt-5.4",
            context_limit=20_000,
        )
        first_client = ConfiguredScriptedClient(
            first_config,
            [
                error_stream_items(
                    MetadataTracker(llm_param.Cost()),
                    error="model_not_available: active fork compact model is unavailable",
                )
            ],
        )
        second_client = ConfiguredScriptedClient(
            second_config,
            [
                [message.AssistantTextDelta(content="fork summary"), _text_assistant_message("fork summary")],
                [
                    message.AssistantTextDelta(content="done after fork compact"),
                    _text_assistant_message("done after fork compact"),
                ],
            ],
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
        session.append_history(
            [
                message.UserMessage(parts=message.text_parts_from_str("old request")),
                _text_assistant_message("old answer"),
                message.UserMessage(parts=message.text_parts_from_str("recent context " + ("x" * 32_000))),
            ]
        )
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
            system_prompt="main prompt",
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
            )
        )

        collected: list[events.Event] = []
        async for event in executor.run(message.UserInputPayload(text="recent context")):
            collected.append(event)

        assert len(first_client.calls) == 1
        assert len(second_client.calls) == 2
        assert second_client.calls[0].system == "main prompt"
        assert second_client.calls[0].tools == []
        fallback_events = [e for e in collected if isinstance(e, events.FallbackModelConfigWarnEvent)]
        assert len(fallback_events) == 1
        assert fallback_events[0].from_provider == "openai"
        assert fallback_events[0].to_provider == "openrouter"
        compaction_events = [e for e in collected if isinstance(e, events.CompactionEndEvent) and not e.aborted]
        assert len(compaction_events) == 1
        assert any(isinstance(item, message.CompactionEntry) for item in session.conversation_history)
        assert "done after fork compact" in [e.task_result for e in collected if isinstance(e, events.TaskFinishEvent)]

    arun(_test())


def test_fork_compaction_uses_explicit_compact_client_for_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_dir = tmp_path / "project"
    project_dir.mkdir()

    def _always_compact(*, session: Session, config: Any, llm_config: Any) -> bool:
        del session, config, llm_config
        return True

    monkeypatch.setattr(task_module, "should_compact_threshold", _always_compact)

    async def _test() -> None:
        main_config = llm_param.LLMConfigParameter(
            provider_name="openai",
            protocol=llm_param.LLMClientProtocol.OPENAI,
            model_id="gpt-5.5",
            context_limit=20_000,
        )
        fallback_config = llm_param.LLMConfigParameter(
            provider_name="openrouter",
            protocol=llm_param.LLMClientProtocol.OPENAI,
            model_id="gpt-5.4",
            context_limit=20_000,
        )
        main_client = ConfiguredScriptedClient(
            main_config,
            [
                [
                    message.AssistantTextDelta(content="done after explicit compact"),
                    _text_assistant_message("done after explicit compact"),
                ]
            ],
        )
        first_compact_client = ConfiguredScriptedClient(
            main_config,
            [
                error_stream_items(
                    MetadataTracker(llm_param.Cost()),
                    error="model_not_available: explicit compact fork model is unavailable",
                )
            ],
        )
        second_compact_client = ConfiguredScriptedClient(
            fallback_config,
            [
                [
                    message.AssistantTextDelta(content="fallback compact summary"),
                    _text_assistant_message("fallback compact summary"),
                ]
            ],
        )

        def _create_llm_client(config: llm_param.LLMConfigParameter) -> LLMClientABC:
            return first_compact_client if config.provider_name == "openai" else second_compact_client

        monkeypatch.setattr(runtime_llm, "create_llm_client", _create_llm_client)

        compact_client = FallbackLLMClient(
            [
                ModelConfigCandidate(
                    selector="gpt-5.5@openai",
                    model_name="gpt-5.5",
                    provider="openai",
                    llm_config=main_config,
                ),
                ModelConfigCandidate(
                    selector="gpt-5.4@openrouter",
                    model_name="gpt-5.4",
                    provider="openrouter",
                    llm_config=fallback_config,
                ),
            ]
        )

        session = Session.create(work_dir=project_dir)
        session.append_history(
            [
                message.UserMessage(parts=message.text_parts_from_str("old request")),
                _text_assistant_message("old answer"),
                message.UserMessage(parts=message.text_parts_from_str("recent context " + ("x" * 32_000))),
            ]
        )
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
            llm_client=main_client,
            system_prompt="main prompt",
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
                compact_llm_client=compact_client,
            )
        )

        collected: list[events.Event] = []
        async for event in executor.run(message.UserInputPayload(text="recent context")):
            collected.append(event)

        assert len(first_compact_client.calls) == 1
        assert len(second_compact_client.calls) == 1
        assert len(main_client.calls) == 1
        assert first_compact_client.calls[0].system == "main prompt"
        assert first_compact_client.calls[0].tools == []
        fallback_events = [e for e in collected if isinstance(e, events.FallbackModelConfigWarnEvent)]
        assert len(fallback_events) == 1
        assert fallback_events[0].from_provider == "openai"
        assert fallback_events[0].to_provider == "openrouter"
        assert "done after explicit compact" in [
            e.task_result for e in collected if isinstance(e, events.TaskFinishEvent)
        ]

    arun(_test())


def test_stream_error_does_not_trigger_cache_break(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Stream-error steps must not emit UsageEvent: empty usage would otherwise
    show up as a false prompt-cache-break alert (cached tokens dropping to 0)."""
    project_dir = tmp_path / "project"
    project_dir.mkdir()

    # Usage with a real cached-token baseline, mimicking a healthy cached step.
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

        # Step 1: healthy response establishes cached-token baseline via tool call.
        harness.fake_llm.enqueue(
            message.AssistantMessage(
                parts=[message.ToolCallPart(call_id="call-1", tool_name="echo", arguments_json='{"text": "hi"}')],
                stop_reason="tool_use",
                usage=cached_usage,
            ),
        )
        # Step 2: LLM client signals a mid-stream network failure. Matches real
        # client behavior: StreamErrorItem + AssistantMessage(stop_reason="error",
        # usage=<empty>). Retry attempt 1 emits the StreamErrorItem again, retry
        # attempt 2 recovers.
        harness.fake_llm.enqueue(
            message.StreamErrorItem(error="RemoteProtocolError peer closed connection"),
            message.AssistantMessage(parts=[], stop_reason="error", usage=Usage()),
        )
        # Step 2 recovery: same prompt, cache still warm.
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

        error_events = [e for e in collected if isinstance(e, events.ErrorEvent)]
        error_messages = [e.error_message for e in error_events]
        # Retry happened.
        assert any(e.can_retry for e in error_events)
        # But no false cache-break alert despite cached 52,000 -> 0 on the error step.
        assert not any("cache break" in msg.lower() for msg in error_messages)

        # Error step's empty usage was not surfaced as a UsageEvent.
        usage_events = [e for e in collected if isinstance(e, events.UsageEvent)]
        assert usage_events, "expected successful turns to still emit UsageEvent"
        for ue in usage_events:
            assert ue.usage.input_tokens > 0 or ue.usage.cached_tokens > 0

    arun(_test())


@pytest.mark.parametrize(
    "parts",
    [[], [message.ThinkingTextPart(text="unfinished", reasoning_field="reasoning_content")]],
    ids=["empty", "reasoning-only"],
)
def test_empty_response_triggers_retry_error_event(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, parts: list[message.Part]
) -> None:
    """Empty model responses emit a retryable ErrorEvent before retrying."""
    monkeypatch.setattr(task_module, "EMPTY_RESPONSE_CONTINUATION_PROMPT", "RETRY_SENTINEL")
    project_dir = tmp_path / "project"
    project_dir.mkdir()

    async def _test() -> None:
        harness = await create_harness(work_dir=project_dir, monkeypatch=monkeypatch)

        incomplete = message.AssistantMessage(parts=parts, usage=_make_usage())
        harness.fake_llm.enqueue(incomplete)

        def recover(param: llm_param.LLMCallParameter) -> list[message.LLMStreamItem]:
            payload, _ = build_payload(param)
            assert all(item["role"] != "assistant" for item in payload["messages"])
            return [message.AssistantTextDelta(content="recovered"), _text_assistant_message("recovered")]

        harness.fake_llm.enqueue_factory(recover)

        collected = await harness.run_task("try again")

        error_events = [e for e in collected if isinstance(e, events.ErrorEvent)]
        assert len(error_events) == 1
        assert error_events[0].can_retry is True
        assert error_events[0].error_message == "Empty response from model, retrying 1/3"

        user_texts = harness.get_user_texts()
        assert len(user_texts) == 2
        assert user_texts[0] == "try again"
        assert user_texts[1] == "RETRY_SENTINEL"
        assert "recovered" in harness.get_assistant_texts()
        assert incomplete in harness.get_history_messages()

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
        assert events.StepStartEvent in event_types
        assert events.StepEndEvent in event_types
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


def test_task_file_change_summary_uses_tool_records_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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
        assert set(files) == {ignored_path}
        assert files[ignored_path].added == 1
        assert files[ignored_path].removed == 0
        assert files[ignored_path].created is True
        assert existing_path not in files
        assert created_path not in files
        assert preexisting_path not in files

        assert harness.session.file_change_summary.edited_files == []
        assert harness.session.file_change_summary.created_files == [str(ignored_path)]
        assert harness.session.file_change_summary.diff_lines_added == 1
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


def test_multi_step_tool_loop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Two consecutive tool calls before final text (3 turns total)."""
    project_dir = tmp_path / "project"
    project_dir.mkdir()

    async def _test() -> None:
        harness = await create_harness(
            work_dir=project_dir,
            tools={"echo": MockEchoTool},
            monkeypatch=monkeypatch,
        )

        # Step 1: tool call
        harness.fake_llm.enqueue(
            _tool_call_assistant_message([("echo", "call_1", '{"text":"step1"}')]),
        )
        # Step 2: another tool call
        harness.fake_llm.enqueue(
            _tool_call_assistant_message([("echo", "call_2", '{"text":"step2"}')]),
        )
        # Step 3: final text
        harness.fake_llm.enqueue(
            message.AssistantTextDelta(content="finished"),
            _text_assistant_message("finished"),
        )

        collected = await harness.run_task("multi step")

        # 3 turns
        step_starts = [e for e in collected if isinstance(e, events.StepStartEvent)]
        step_ends = [e for e in collected if isinstance(e, events.StepEndEvent)]
        assert len(step_starts) == 3
        assert len(step_ends) == 3

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
