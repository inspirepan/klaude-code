from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi import HTTPException

from klaude_code.agent.attachments.autonomy import autonomy_attachment
from klaude_code.agent.attachments.state import reset_attachment_loaded_flags
from klaude_code.protocol import message, op
from klaude_code.protocol.message import QueuedUserInput, UserInputPayload
from klaude_code.server.headless import HeadlessRuntime, QueuedRun, format_tool_call_activity
from klaude_code.server.routes.headless import _resolve_target  # pyright: ignore[reportPrivateUsage]
from klaude_code.server.session_index import SessionSummary
from klaude_code.session.session import Session
from klaude_code.session.store_registry import get_store_for_path


def _summary(session_id: str, *, name: str | None = None, archived: bool = False) -> SessionSummary:
    return SessionSummary(
        id=session_id,
        created_at=1.0,
        updated_at=2.0,
        work_dir="/tmp/x",
        title=None,
        user_messages=[],
        messages_count=0,
        model_name=None,
        archived=archived,
        todos=[],
        file_change_summary={},
        name=name,
    )


class TestResolveTarget:
    def test_exact_id(self) -> None:
        summaries = [_summary("abcd1234"), _summary("abzz9999")]
        assert _resolve_target(summaries, "abcd1234").id == "abcd1234"

    def test_unique_prefix(self) -> None:
        summaries = [_summary("abcd1234"), _summary("efgh5678")]
        assert _resolve_target(summaries, "ab").id == "abcd1234"

    def test_name_match_beats_prefix(self) -> None:
        summaries = [_summary("abcd1234"), _summary("efgh5678", name="abcd")]
        assert _resolve_target(summaries, "abcd").id == "efgh5678"

    def test_ambiguous_prefix_lists_candidates(self) -> None:
        summaries = [_summary("abcd1234"), _summary("abzz9999")]
        with pytest.raises(HTTPException) as exc_info:
            _resolve_target(summaries, "ab")
        assert exc_info.value.status_code == 400
        detail = exc_info.value.detail
        assert isinstance(detail, dict)
        assert set(detail["candidates"]) == {"abcd1234", "abzz9999"}

    def test_archived_name_yields_to_active(self) -> None:
        summaries = [_summary("abcd1234", name="dup", archived=True), _summary("efgh5678", name="dup")]
        assert _resolve_target(summaries, "dup").id == "efgh5678"

    def test_unknown_target_404(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            _resolve_target([_summary("abcd1234")], "zzzz")
        assert exc_info.value.status_code == 404


class TestFormatToolCallActivity:
    def test_extracts_primary_argument(self) -> None:
        assert format_tool_call_activity("Bash", '{"command": "uv run pytest"}') == "Bash: uv run pytest"

    def test_truncates_long_arguments(self) -> None:
        label = format_tool_call_activity("Bash", '{"command": "' + "x" * 200 + '"}', max_len=40)
        assert len(label) == 40
        assert label.endswith("…")

    def test_non_json_arguments(self) -> None:
        assert format_tool_call_activity("Edit", "not json") == "Edit: not json"

    def test_no_arguments(self) -> None:
        assert format_tool_call_activity("TodoWrite", "") == "TodoWrite"


class TestAutonomyAttachment:
    def test_injects_once_for_headless(self, tmp_path: Path) -> None:
        session = Session.create(work_dir=tmp_path)
        session.spawn_kind = "headless"
        first = asyncio.run(autonomy_attachment(session))
        assert first is not None
        part = first.parts[0]
        assert isinstance(part, message.TextPart)
        assert "running unattended" in part.text
        assert asyncio.run(autonomy_attachment(session)) is None

    def test_skips_interactive_sessions(self, tmp_path: Path) -> None:
        session = Session.create(work_dir=tmp_path)
        assert asyncio.run(autonomy_attachment(session)) is None

    def test_reinjects_after_compaction_reset(self, tmp_path: Path) -> None:
        session = Session.create(work_dir=tmp_path)
        session.spawn_kind = "headless"
        assert asyncio.run(autonomy_attachment(session)) is not None
        reset_attachment_loaded_flags(session.file_tracker)
        assert asyncio.run(autonomy_attachment(session)) is not None


def test_runtime_rebuild_restores_queued_follow_up_and_failed(
    isolated_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    del isolated_home
    runtime = cast(Any, SimpleNamespace(session_registry=SimpleNamespace()))

    queued = Session.create(work_dir=tmp_path)
    queued.spawn_kind = "headless"
    queued.ensure_meta_exists()
    first_runtime = HeadlessRuntime(runtime, max_running=1)
    monkeypatch.setattr(first_runtime, "_pump", lambda: None)
    asyncio.run(first_runtime.spawn(session_id=queued.id, prompt=UserInputPayload(text="durable"), work_dir=tmp_path))

    follow_up = Session.create(work_dir=tmp_path)
    follow_up.spawn_kind = "headless"
    follow_up.ensure_meta_exists()
    follow_up.set_follow_up_queue(
        [
            QueuedUserInput(input=UserInputPayload(text="one"), enqueued_at=2.0),
            QueuedUserInput(input=UserInputPayload(text="two"), enqueued_at=3.0),
        ]
    )

    failed = Session.create(work_dir=tmp_path)
    failed.spawn_kind = "headless"
    failed.ensure_meta_exists()
    Session.persist_headless_failed(failed.id, tmp_path, failed=True)

    summaries = [
        SimpleNamespace(
            id=session.id,
            spawn_kind="headless",
            work_dir=str(tmp_path),
            created_at=float(index + 1),
        )
        for index, session in enumerate((queued, follow_up, failed))
    ]
    rebuilt = HeadlessRuntime(runtime, max_running=1)
    monkeypatch.setattr(rebuilt, "_pump", lambda: None)
    rebuilt.restore(cast(list[SessionSummary], summaries))

    assert set(rebuilt.queued_session_ids()) == {queued.id, follow_up.id}
    restored_queued = Session.load_meta(queued.id, work_dir=tmp_path)
    assert restored_queued.headless_queued_turn is not None
    assert restored_queued.headless_queued_turn.input == UserInputPayload(text="durable")
    restored_follow_up = Session.load_meta(follow_up.id, work_dir=tmp_path)
    assert [item.input.text for item in restored_follow_up.follow_up_queue] == ["one", "two"]
    assert rebuilt.tracker.is_failed(failed.id)


def test_cancel_before_history_confirmation_keeps_durable_turn(
    isolated_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    del isolated_home

    async def _test() -> None:
        session = Session.create(work_dir=tmp_path)
        session.spawn_kind = "headless"
        session.ensure_meta_exists()
        turn_id = "durable-turn"
        Session.persist_headless_queued_turn(
            session.id,
            tmp_path,
            queued_turn=QueuedUserInput(id=turn_id, input=UserInputPayload(text="keep me"), enqueued_at=1.0),
        )
        flush_confirmation = asyncio.Event()

        async def _wait_for_flush(_session: Session) -> None:
            await flush_confirmation.wait()

        monkeypatch.setattr(Session, "wait_for_flush", _wait_for_flush)
        actor = SimpleNamespace(get_agent=lambda: SimpleNamespace(session=session))

        async def _submit(operation: Any) -> str:
            session.append_history(
                [message.UserMessage(id=operation.id, parts=message.text_parts_from_str(operation.input.text))]
            )
            return cast(str, operation.id)

        runtime_facade = cast(
            Any,
            SimpleNamespace(
                session_registry=SimpleNamespace(get_session_actor=lambda _session_id: actor),
                emit_event=lambda _event: asyncio.sleep(0),
                submit=_submit,
                wait_for=lambda _operation_id: asyncio.sleep(0),
            ),
        )
        runtime = HeadlessRuntime(runtime_facade)
        task = asyncio.create_task(
            runtime._start_turn(  # pyright: ignore[reportPrivateUsage]
                session.id,
                UserInputPayload(text="keep me"),
                turn_id=turn_id,
                clear_queued_work_dir=tmp_path,
            )
        )
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert Session.load_meta(session.id, tmp_path).headless_queued_turn is not None
        flush_confirmation.set()
        await asyncio.sleep(0)

    asyncio.run(_test())


def test_queued_turn_clear_does_not_remove_a_later_turn(isolated_home: Path, tmp_path: Path) -> None:
    del isolated_home
    session = Session.create(work_dir=tmp_path)
    session.spawn_kind = "headless"
    session.ensure_meta_exists()
    Session.persist_headless_queued_turn(
        session.id,
        tmp_path,
        queued_turn=QueuedUserInput(id="first", input=UserInputPayload(text="first"), enqueued_at=1.0),
    )
    Session.persist_headless_queued_turn(
        session.id,
        tmp_path,
        queued_turn=QueuedUserInput(id="second", input=UserInputPayload(text="second"), enqueued_at=2.0),
    )

    assert not Session.persist_headless_queued_turn(
        session.id,
        tmp_path,
        expected_turn_id="first",
    )
    restored = Session.load_meta(session.id, tmp_path)
    assert restored.headless_queued_turn is not None
    assert restored.headless_queued_turn.id == "second"
    assert restored.headless_queued_turn.input == UserInputPayload(text="second")


def test_legacy_queued_turn_is_read_once_and_new_write_removes_old_keys(isolated_home: Path, tmp_path: Path) -> None:
    del isolated_home
    session = Session.create(work_dir=tmp_path)
    session.ensure_meta_exists()
    store = get_store_for_path(tmp_path)
    assert store.update_meta(
        session.id,
        {
            "headless_queued_prompt": {"text": "legacy"},
            "headless_queued_turn_id": "legacy-turn",
            "headless_queued_at": 12.5,
        },
    )

    loaded = Session.load_meta(session.id, tmp_path)
    assert loaded.headless_queued_turn == QueuedUserInput(
        id="legacy-turn", input=UserInputPayload(text="legacy"), enqueued_at=12.5
    )
    assert Session.persist_headless_queued_turn(session.id, tmp_path, expected_turn_id="legacy-turn")
    cleared = store.load_meta(session.id)
    assert cleared is not None
    assert (
        not {
            "headless_queued_turn",
            "headless_queued_prompt",
            "headless_queued_turn_id",
            "headless_queued_at",
        }
        & cleared.keys()
    )

    replacement = QueuedUserInput(id="new-turn", input=UserInputPayload(text="new"), enqueued_at=13.0)
    assert Session.persist_headless_queued_turn(session.id, tmp_path, queued_turn=replacement)

    raw = store.load_meta(session.id)
    assert raw is not None
    assert raw["headless_queued_turn"] == replacement.model_dump(mode="json", exclude_none=True)
    assert not {"headless_queued_prompt", "headless_queued_turn_id", "headless_queued_at"} & raw.keys()


def test_restore_requeues_turn_when_only_user_message_is_persisted(
    isolated_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    del isolated_home

    async def _seed() -> Session:
        session = Session.create(work_dir=tmp_path)
        session.spawn_kind = "headless"
        session.ensure_meta_exists()
        Session.persist_headless_queued_turn(
            session.id,
            tmp_path,
            queued_turn=QueuedUserInput(
                id="persisted-turn", input=UserInputPayload(text="already durable"), enqueued_at=1.0
            ),
        )
        session.append_history(
            [message.UserMessage(id="persisted-turn", parts=message.text_parts_from_str("already durable"))]
        )
        await session.wait_for_flush()
        return session

    session = asyncio.run(_seed())
    runtime = HeadlessRuntime(cast(Any, SimpleNamespace(session_registry=SimpleNamespace())))
    monkeypatch.setattr(runtime, "_pump", lambda: None)
    runtime.restore(
        [
            cast(
                SessionSummary,
                SimpleNamespace(
                    id=session.id,
                    spawn_kind="headless",
                    work_dir=str(tmp_path),
                    created_at=1.0,
                ),
            )
        ]
    )

    assert runtime.queued_session_ids() == [session.id]
    assert Session.load_meta(session.id, tmp_path).headless_queued_turn is not None


def test_restore_acknowledges_completed_turn_before_queue_ack(
    isolated_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    del isolated_home
    session = Session.create(work_dir=tmp_path)
    session.spawn_kind = "headless"
    session.ensure_meta_exists()
    Session.persist_headless_queued_turn(
        session.id,
        tmp_path,
        queued_turn=QueuedUserInput(
            id="completed-turn", input=UserInputPayload(text="already completed"), enqueued_at=1.0
        ),
    )
    Session.persist_headless_completed_turn(session.id, tmp_path, turn_id="completed-turn")

    runtime = HeadlessRuntime(cast(Any, SimpleNamespace(session_registry=SimpleNamespace())))
    monkeypatch.setattr(runtime, "_pump", lambda: None)
    runtime.restore(
        [
            cast(
                SessionSummary,
                SimpleNamespace(
                    id=session.id,
                    spawn_kind="headless",
                    work_dir=str(tmp_path),
                    created_at=1.0,
                ),
            )
        ]
    )

    assert runtime.queued_session_ids() == []
    assert Session.load_meta(session.id, tmp_path).headless_queued_turn is None


def test_cancelled_follow_up_stays_queued_until_turn_confirmation(
    isolated_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    del isolated_home

    async def _test() -> None:
        queued = QueuedUserInput(id="follow-up", input=UserInputPayload(text="do not lose"), enqueued_at=1.0)
        session = Session.create(work_dir=tmp_path)
        session.spawn_kind = "headless"
        session.follow_up_queue = [queued]
        session.ensure_meta_exists()

        class FakeAgent:
            def __init__(self) -> None:
                self.session = session
                self.queue = list(session.follow_up_queue)
                self.in_flight: QueuedUserInput | None = None

            def peek_next_follow_up_record(self) -> QueuedUserInput | None:
                return self.queue[0] if self.queue else None

            def begin_follow_up(self, item_id: str) -> bool:
                if not self.queue or self.queue[0].id != item_id:
                    return False
                self.in_flight = self.queue.pop(0)
                return True

            def acknowledge_follow_up(self, item_id: str, *, next_enqueued_at: float | None = None) -> bool:
                del next_enqueued_at
                if self.in_flight is None or self.in_flight.id != item_id:
                    return False
                self.in_flight = None
                self.session.set_follow_up_queue(self.queue)
                return True

            def abort_follow_up(self, item_id: str) -> bool:
                if self.in_flight is None or self.in_flight.id != item_id:
                    return False
                self.queue.insert(0, self.in_flight)
                self.in_flight = None
                self.session.set_follow_up_queue(self.queue)
                return True

            def follow_up_snapshot(self) -> tuple[UserInputPayload, ...]:
                return tuple(item.input for item in self.queue)

        agent = FakeAgent()
        actor = SimpleNamespace(get_agent=lambda: agent)
        turn_finished = asyncio.Event()

        async def _submit(operation: Any) -> str:
            session.append_history(
                [message.UserMessage(id=operation.id, parts=message.text_parts_from_str(operation.input.text))]
            )
            return cast(str, operation.id)

        runtime_facade = cast(
            Any,
            SimpleNamespace(
                session_registry=SimpleNamespace(get_session_actor=lambda _session_id: actor),
                emit_event=lambda _event: asyncio.sleep(0),
                submit=_submit,
                wait_for=lambda _operation_id: turn_finished.wait(),
            ),
        )
        runtime = HeadlessRuntime(runtime_facade)
        monkeypatch.setattr(runtime, "_should_compact_before_run", lambda _agent: False)
        task = asyncio.create_task(runtime._run_one_follow_up(agent))  # pyright: ignore[reportPrivateUsage]
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        restored = Session.load_meta(session.id, tmp_path)
        assert [item.id for item in restored.follow_up_queue] == [queued.id]
        assert [item.id for item in agent.queue] == [queued.id]

    asyncio.run(_test())


def test_restore_acknowledges_persisted_follow_up_and_keeps_next(
    isolated_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    del isolated_home

    async def _seed() -> Session:
        first = QueuedUserInput(id="first", input=UserInputPayload(text="first"), enqueued_at=1.0)
        second = QueuedUserInput(id="second", input=UserInputPayload(text="second"), enqueued_at=2.0)
        session = Session.create(work_dir=tmp_path)
        session.spawn_kind = "headless"
        session.follow_up_queue = [first, second]
        session.ensure_meta_exists()
        session.append_history([message.UserMessage(id=first.id, parts=message.text_parts_from_str("first"))])
        await session.wait_for_flush()
        Session.persist_headless_completed_turn(session.id, tmp_path, turn_id=first.id)
        return session

    session = asyncio.run(_seed())
    runtime = HeadlessRuntime(cast(Any, SimpleNamespace(session_registry=SimpleNamespace())))
    monkeypatch.setattr(runtime, "_pump", lambda: None)
    runtime.restore(
        [
            cast(
                SessionSummary,
                SimpleNamespace(
                    id=session.id,
                    spawn_kind="headless",
                    work_dir=str(tmp_path),
                    created_at=1.0,
                ),
            )
        ]
    )

    restored = Session.load_meta(session.id, tmp_path)
    assert [item.id for item in restored.follow_up_queue] == ["second"]
    assert runtime.queued_session_ids() == [session.id]


def test_headless_follow_ups_are_fifo_and_fair(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    async def _test() -> None:
        records = {
            "first": [
                QueuedUserInput(id="first-1", input=UserInputPayload(text="first-1"), enqueued_at=1.0),
                QueuedUserInput(id="first-2", input=UserInputPayload(text="first-2"), enqueued_at=3.0),
            ],
            "second": [QueuedUserInput(id="second-1", input=UserInputPayload(text="second-1"), enqueued_at=2.0)],
        }

        class FakeAgent:
            def __init__(self, session_id: str) -> None:
                self.session = SimpleNamespace(id=session_id, work_dir=tmp_path)

            def peek_next_follow_up_record(self) -> QueuedUserInput | None:
                queue = records[self.session.id]
                return queue[0] if queue else None

        agents = {session_id: FakeAgent(session_id) for session_id in records}
        registry = SimpleNamespace(
            get_session_actor=lambda session_id: SimpleNamespace(get_agent=lambda: agents[session_id])
        )
        runtime = HeadlessRuntime(cast(Any, SimpleNamespace(session_registry=registry)), max_running=1)
        execution_order: list[str] = []

        async def _run_one(entry: Any) -> None:
            queue = records[entry.session_id]
            execution_order.append(queue.pop(0).id)

        monkeypatch.setattr(runtime, "_run_headless_follow_up", _run_one)
        runtime._enqueue(  # pyright: ignore[reportPrivateUsage]
            cast(Any, SimpleNamespace(session_id="first", prompt=None, work_dir=tmp_path, kind="follow_up"))
        )
        runtime._enqueue(  # pyright: ignore[reportPrivateUsage]
            cast(Any, SimpleNamespace(session_id="second", prompt=None, work_dir=tmp_path, kind="follow_up"))
        )
        runtime._pump()  # pyright: ignore[reportPrivateUsage]
        while runtime._running or runtime.queued_session_ids():  # pyright: ignore[reportPrivateUsage]
            await asyncio.sleep(0)

        assert execution_order == ["first-1", "second-1", "first-2"]

    asyncio.run(_test())


def test_send_waits_for_launch_initialization_handoff(
    isolated_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    del isolated_home

    async def _test() -> None:
        session = Session.create(work_dir=tmp_path)
        session.spawn_kind = "headless"
        session.ensure_meta_exists()
        init_started = asyncio.Event()
        finish_init = asyncio.Event()
        finish_turn = asyncio.Event()
        run_operation_id: str | None = None
        agent: Any | None = None

        class FakeAgent:
            def __init__(self) -> None:
                self.session = session

            def peek_next_follow_up(self) -> UserInputPayload | None:
                queue = self.session.follow_up_queue
                return queue[0].input if queue else None

            def peek_next_follow_up_record(self) -> QueuedUserInput | None:
                queue = self.session.follow_up_queue
                return queue[0] if queue else None

            def follow_up(self, prompt: UserInputPayload) -> None:
                self.session.set_follow_up_queue([*self.session.follow_up_queue, QueuedUserInput(input=prompt)])

        actor = SimpleNamespace(
            get_agent=lambda: agent,
            snapshot=lambda: SimpleNamespace(is_idle=False),
        )

        async def _submit_and_wait(_operation: Any) -> None:
            nonlocal agent
            init_started.set()
            await finish_init.wait()
            agent = FakeAgent()

        async def _submit(operation: Any) -> str:
            nonlocal run_operation_id
            assert agent is not None
            if isinstance(operation, op.RunAgentOperation):
                run_operation_id = operation.id
            else:
                assert isinstance(operation, op.FollowUpAgentOperation)
                agent.follow_up(operation.input)
            return cast(str, operation.id)

        async def _wait_for(operation_id: str) -> None:
            if operation_id == run_operation_id:
                await finish_turn.wait()

        facade = cast(
            Any,
            SimpleNamespace(
                session_registry=SimpleNamespace(get_session_actor=lambda _session_id: actor),
                submit_and_wait=_submit_and_wait,
                submit=_submit,
                wait_for=_wait_for,
                emit_event=lambda _event: asyncio.sleep(0),
            ),
        )
        runtime = HeadlessRuntime(facade)
        monkeypatch.setattr(runtime, "_schedule_follow_up_drain", lambda _session_id: None)
        runtime._enqueue(  # pyright: ignore[reportPrivateUsage]
            QueuedRun(session.id, QueuedUserInput(input=UserInputPayload(text="first")), tmp_path)
        )
        runtime._pump()  # pyright: ignore[reportPrivateUsage]
        await init_started.wait()

        send_task = asyncio.create_task(
            runtime.send(session_id=session.id, prompt=UserInputPayload(text="second"), work_dir=tmp_path)
        )
        await asyncio.sleep(0)
        assert not send_task.done()
        finish_init.set()

        assert await asyncio.wait_for(send_task, timeout=1) == "queued"
        assert [item.input.text for item in Session.load_meta(session.id, tmp_path).follow_up_queue] == ["second"]
        finish_turn.set()
        await runtime.aclose()

    asyncio.run(_test())


def test_concurrent_idle_sends_preserve_both_turns(isolated_home: Path, tmp_path: Path) -> None:
    del isolated_home

    async def _test() -> None:
        session = Session.create(work_dir=tmp_path)
        session.spawn_kind = "headless"
        session.ensure_meta_exists()

        class FakeAgent:
            def __init__(self) -> None:
                self.session = session

            def peek_next_follow_up(self) -> UserInputPayload | None:
                queue = self.session.follow_up_queue
                return queue[0].input if queue else None

            def peek_next_follow_up_record(self) -> QueuedUserInput | None:
                queue = self.session.follow_up_queue
                return queue[0] if queue else None

            def follow_up(self, prompt: UserInputPayload) -> None:
                self.session.set_follow_up_queue([*self.session.follow_up_queue, QueuedUserInput(input=prompt)])

        agent = FakeAgent()
        actor = SimpleNamespace(get_agent=lambda: agent, snapshot=lambda: SimpleNamespace(is_idle=True))

        async def _submit(operation: Any) -> str:
            assert isinstance(operation, op.FollowUpAgentOperation)
            agent.follow_up(operation.input)
            return operation.id

        facade = cast(
            Any,
            SimpleNamespace(
                session_registry=SimpleNamespace(get_session_actor=lambda _session_id: actor),
                submit=_submit,
                wait_for=lambda _operation_id: asyncio.sleep(0),
            ),
        )
        runtime = HeadlessRuntime(facade, max_running=1)
        runtime._running.add("slot-blocker")  # pyright: ignore[reportPrivateUsage]

        results = await asyncio.gather(
            runtime.send(session_id=session.id, prompt=UserInputPayload(text="first"), work_dir=tmp_path),
            runtime.send(session_id=session.id, prompt=UserInputPayload(text="second"), work_dir=tmp_path),
        )

        assert results == ["queued", "queued"]
        queued = Session.load_meta(session.id, tmp_path)
        assert queued.headless_queued_turn is not None
        assert queued.headless_queued_turn.input == UserInputPayload(text="first")
        assert [item.input.text for item in queued.follow_up_queue] == ["second"]
        await runtime.aclose()

    asyncio.run(_test())


def test_send_propagates_launch_initialization_failure(tmp_path: Path) -> None:
    async def _test() -> None:
        init_started = asyncio.Event()
        fail_init = asyncio.Event()
        actor = SimpleNamespace(get_agent=lambda: None, snapshot=lambda: SimpleNamespace(is_idle=False))

        async def _submit_and_wait(_operation: Any) -> None:
            init_started.set()
            await fail_init.wait()
            raise RuntimeError("init exploded")

        facade = cast(
            Any,
            SimpleNamespace(
                session_registry=SimpleNamespace(get_session_actor=lambda _session_id: actor),
                submit_and_wait=_submit_and_wait,
            ),
        )
        runtime = HeadlessRuntime(facade)
        runtime._enqueue(  # pyright: ignore[reportPrivateUsage]
            QueuedRun("failed", QueuedUserInput(input=UserInputPayload(text="first")), tmp_path)
        )
        runtime._pump()  # pyright: ignore[reportPrivateUsage]
        await init_started.wait()

        send_task = asyncio.create_task(
            runtime.send(session_id="failed", prompt=UserInputPayload(text="second"), work_dir=tmp_path)
        )
        await asyncio.sleep(0)
        fail_init.set()

        with pytest.raises(RuntimeError, match="init exploded"):
            await asyncio.wait_for(send_task, timeout=1)
        await runtime.aclose()

    asyncio.run(_test())


def test_shutdown_cancels_send_waiting_for_launch_initialization(isolated_home: Path, tmp_path: Path) -> None:
    del isolated_home

    async def _test() -> None:
        session = Session.create(work_dir=tmp_path)
        session.spawn_kind = "headless"
        session.ensure_meta_exists()
        init_started = asyncio.Event()
        submitted: list[op.Operation] = []
        actor = SimpleNamespace(get_agent=lambda: None, snapshot=lambda: SimpleNamespace(is_idle=False))

        async def _submit_and_wait(operation: Any) -> None:
            submitted.append(operation)
            init_started.set()
            await asyncio.Event().wait()

        facade = cast(
            Any,
            SimpleNamespace(
                session_registry=SimpleNamespace(get_session_actor=lambda _session_id: actor),
                submit_and_wait=_submit_and_wait,
            ),
        )
        runtime = HeadlessRuntime(facade)
        assert (
            await runtime.spawn(
                session_id=session.id,
                prompt=UserInputPayload(text="first"),
                work_dir=tmp_path,
            )
            == "running"
        )
        await init_started.wait()

        send_task = asyncio.create_task(
            runtime.send(session_id=session.id, prompt=UserInputPayload(text="second"), work_dir=tmp_path)
        )
        await asyncio.sleep(0)
        await runtime.aclose()

        with pytest.raises(asyncio.CancelledError):
            await send_task
        assert len(submitted) == 1
        assert isinstance(submitted[0], op.InitAgentOperation)
        restored = Session.load_meta(session.id, work_dir=tmp_path)
        assert restored.headless_queued_turn is not None
        assert restored.headless_queued_turn.input == UserInputPayload(text="first")
        assert restored.headless_queued_turn.id is not None

    asyncio.run(_test())


def test_steer_reserves_next_turn_until_interrupted_run_releases_slot(
    isolated_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    del isolated_home

    async def _test() -> None:
        session = Session.create(work_dir=tmp_path)
        session.spawn_kind = "headless"
        session.ensure_meta_exists()
        interrupt_started = asyncio.Event()
        finish_interrupt = asyncio.Event()
        launch_started = asyncio.Event()
        finish_launch = asyncio.Event()
        actor_busy = True

        actor = SimpleNamespace(
            get_agent=lambda: SimpleNamespace(session=session),
            snapshot=lambda: SimpleNamespace(is_idle=not actor_busy),
        )

        async def _submit_and_wait(operation: Any) -> None:
            nonlocal actor_busy
            assert isinstance(operation, op.InterruptOperation)
            interrupt_started.set()
            await finish_interrupt.wait()
            actor_busy = False

        facade = cast(
            Any,
            SimpleNamespace(
                session_registry=SimpleNamespace(get_session_actor=lambda _session_id: actor),
                submit_and_wait=_submit_and_wait,
            ),
        )
        runtime = HeadlessRuntime(facade, max_running=1)
        runtime._running.add(session.id)  # pyright: ignore[reportPrivateUsage]

        async def _launch(entry: QueuedRun) -> None:
            launch_started.set()
            await finish_launch.wait()
            runtime._running.discard(entry.session_id)  # pyright: ignore[reportPrivateUsage]

        monkeypatch.setattr(runtime, "_launch_logged", _launch)
        steer_task = asyncio.create_task(
            runtime.steer(
                session_id=session.id,
                prompt=UserInputPayload(text="new direction"),
                work_dir=tmp_path,
            )
        )

        await interrupt_started.wait()
        assert runtime.has_pending(session.id)

        # The old operation can finish naturally while its interrupt is in
        # flight. The reserved turn must remain queued, not expose idle or run
        # until the interrupt operation itself completes.
        runtime._running.discard(session.id)  # pyright: ignore[reportPrivateUsage]
        runtime._pump()  # pyright: ignore[reportPrivateUsage]
        assert runtime.is_queued(session.id)
        assert runtime.has_pending(session.id)
        assert not launch_started.is_set()

        finish_interrupt.set()
        assert await asyncio.wait_for(steer_task, timeout=1) == "started"
        await asyncio.wait_for(launch_started.wait(), timeout=1)
        assert runtime.is_running(session.id)

        finish_launch.set()
        await asyncio.sleep(0)
        await runtime.aclose()

    asyncio.run(_test())


def test_latest_queued_steer_wins_when_slots_are_full(isolated_home: Path, tmp_path: Path) -> None:
    del isolated_home

    async def _test() -> None:
        session = Session.create(work_dir=tmp_path)
        session.spawn_kind = "headless"
        session.ensure_meta_exists()
        actor = SimpleNamespace(
            get_agent=lambda: SimpleNamespace(session=session),
            snapshot=lambda: SimpleNamespace(is_idle=True),
        )
        facade = cast(
            Any,
            SimpleNamespace(session_registry=SimpleNamespace(get_session_actor=lambda _session_id: actor)),
        )
        runtime = HeadlessRuntime(facade, max_running=1)
        runtime._running.add("slot-blocker")  # pyright: ignore[reportPrivateUsage]

        assert (
            await runtime.steer(
                session_id=session.id,
                prompt=UserInputPayload(text="first direction"),
                work_dir=tmp_path,
            )
            == "queued"
        )
        assert (
            await runtime.steer(
                session_id=session.id,
                prompt=UserInputPayload(text="latest direction"),
                work_dir=tmp_path,
            )
            == "queued"
        )

        assert runtime.queued_session_ids().count(session.id) == 1
        restored = Session.load_meta(session.id, work_dir=tmp_path)
        assert restored.headless_queued_turn is not None
        assert restored.headless_queued_turn.input == UserInputPayload(text="latest direction")
        await runtime.aclose()

    asyncio.run(_test())


class TestChildSessionIndexing:
    def test_child_with_parent_link_is_indexed(self) -> None:
        from klaude_code.server.session_index import load_session_summary_from_meta

        summary = load_session_summary_from_meta(
            {"id": "child1", "work_dir": "/tmp/x", "parent_session_id": "parent1", "agent_type": "finder"},
            fallback_session_id="child1",
        )
        assert summary is not None
        assert summary.parent_session_id == "parent1"
        assert summary.agent_type == "finder"

    def test_legacy_sub_agent_without_parent_link_stays_hidden(self) -> None:
        from klaude_code.server.session_index import load_session_summary_from_meta

        summary = load_session_summary_from_meta(
            {
                "id": "legacy1",
                "work_dir": "/tmp/x",
                "sub_agent_state": {"sub_agent_type": "Task", "sub_agent_desc": "d", "sub_agent_prompt": "p"},
            },
            fallback_session_id="legacy1",
        )
        assert summary is None

    def test_resolve_target_finds_child_summary(self) -> None:
        parent = _summary("aaaa1111")
        child = SessionSummary(
            id="bbbb2222",
            created_at=1.0,
            updated_at=2.0,
            work_dir="/tmp/x",
            title=None,
            user_messages=[],
            messages_count=0,
            model_name=None,
            archived=False,
            todos=[],
            file_change_summary={},
            parent_session_id="aaaa1111",
        )
        resolved = _resolve_target([parent, child], "bbbb")
        assert resolved.id == "bbbb2222"


def test_latched_queue_notifies_once_and_revives_on_activity(tmp_path: Path) -> None:
    """A failed/stopped latch must be visible (one NoticeEvent per episode)
    and must lift on explicit user activity (mark_session_active)."""
    emitted: list[Any] = []

    class FakeAgent:
        def __init__(self) -> None:
            self.session = SimpleNamespace(id="s1", spawn_kind=None, work_dir=tmp_path)

        def peek_next_follow_up(self) -> UserInputPayload:
            return UserInputPayload(text="queued")

        def follow_up_count(self) -> int:
            return 1

    actor = SimpleNamespace(get_agent=lambda: FakeAgent())

    async def _emit_event(event: Any) -> None:
        emitted.append(event)

    runtime = cast(
        Any,
        SimpleNamespace(
            session_registry=SimpleNamespace(get_session_actor=lambda _sid: actor),
            emit_event=_emit_event,
        ),
    )
    hr = HeadlessRuntime(runtime, max_running=1)

    async def scenario() -> None:
        from klaude_code.protocol import events

        hr.tracker.restore_failed("s1")
        hr._schedule_follow_up_drain("s1")  # pyright: ignore[reportPrivateUsage]
        hr._schedule_follow_up_drain("s1")  # pyright: ignore[reportPrivateUsage]
        await asyncio.sleep(0)
        notices = [e for e in emitted if isinstance(e, events.NoticeEvent)]
        assert len(notices) == 1
        assert "paused" in notices[0].content

        hr.mark_session_active("s1")
        assert not hr.tracker.is_failed("s1")

        # A fresh latch episode notifies again.
        hr.tracker.restore_failed("s1")
        hr._schedule_follow_up_drain("s1")  # pyright: ignore[reportPrivateUsage]
        await asyncio.sleep(0)
        notices = [e for e in emitted if isinstance(e, events.NoticeEvent)]
        assert len(notices) == 2

    asyncio.run(scenario())


def test_mark_session_active_lifts_kill_latch(tmp_path: Path) -> None:
    """klaude kill latches the session; TUI attach/submit must lift it or
    follow-ups queued afterwards never drain."""
    del tmp_path
    runtime = cast(Any, SimpleNamespace(session_registry=SimpleNamespace(get_session_actor=lambda _sid: None)))
    hr = HeadlessRuntime(runtime, max_running=1)
    hr._stopped_sessions.add("s1")  # pyright: ignore[reportPrivateUsage]
    hr.tracker.restore_failed("s1")

    hr.mark_session_active("s1")

    assert "s1" not in hr._stopped_sessions  # pyright: ignore[reportPrivateUsage]
    assert not hr.tracker.is_failed("s1")
