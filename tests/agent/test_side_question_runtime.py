# pyright: reportPrivateUsage=false

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from klaude_code.agent.runtime.agent_ops import AgentOperationHandler
from klaude_code.agent.side_question import SideQuestionError, SideQuestionResult
from klaude_code.protocol import events, message, op
from klaude_code.session.session import Session


def _handler(emit: Any) -> AgentOperationHandler:
    """A handler with only the collaborators the side-question path touches."""
    handler = object.__new__(AgentOperationHandler)
    handler._emit_event = emit
    handler._side_question_tasks = {}
    return handler


def _fake_agent(session: Session) -> Any:
    return type("FakeAgent", (), {"session": session, "profile": object()})()


async def _drain(handler: AgentOperationHandler) -> None:
    for pending in list(handler._side_question_tasks.values()):
        await pending.task


def test_side_question_answer_is_persisted_but_kept_out_of_llm_history(
    tmp_path: Path, isolated_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    del isolated_home

    async def _test() -> None:
        emitted: list[Any] = []

        async def _emit(event: Any) -> None:
            emitted.append(event)

        handler = _handler(_emit)
        session = Session(work_dir=tmp_path)
        session.append_history([message.UserMessage(parts=message.text_parts_from_str("implement it"))])

        async def _ensure_agent(_session_id: str) -> Any:
            return _fake_agent(session)

        async def _fake_run(**_kwargs: Any) -> SideQuestionResult:
            return SideQuestionResult(answer="because the prefix matches.", usage=None, cache_hit_rate=0.97)

        monkeypatch.setattr(handler, "ensure_agent", _ensure_agent)
        monkeypatch.setattr("klaude_code.agent.runtime.agent_ops.run_side_question", _fake_run)

        operation = op.AskSideQuestionOperation(session_id=session.id, question="  why cached?  ")
        await handler.ask_side_question(operation)
        await _drain(handler)

        assert isinstance(emitted[0], events.SideQuestionStartEvent)
        assert emitted[0].request_id == operation.id
        assert emitted[0].question == "why cached?"
        assert isinstance(emitted[1], events.SideQuestionEvent)
        assert emitted[1].request_id == operation.id
        assert emitted[1].answer == "because the prefix matches."
        assert emitted[1].cache_hit_rate == 0.97

        entries = [item for item in session.conversation_history if isinstance(item, message.SideQuestionEntry)]
        assert len(entries) == 1
        assert entries[0].question == "why cached?"
        assert entries[0].cache_hit_rate == 0.97
        # The exchange must not reach the model's view of the conversation.
        llm_history = [m for m in session.get_llm_history() if isinstance(m, message.Message)]
        assert all("why cached?" not in message.join_text_parts(m.parts) for m in llm_history)

    asyncio.run(_test())


def test_empty_side_question_is_rejected_without_an_llm_call(
    tmp_path: Path, isolated_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    del isolated_home

    async def _test() -> None:
        emitted: list[Any] = []

        async def _emit(event: Any) -> None:
            emitted.append(event)

        handler = _handler(_emit)
        session = Session(work_dir=tmp_path)

        async def _ensure_agent(_session_id: str) -> Any:
            raise AssertionError("an empty question must be rejected before the agent is touched")

        async def _fail_run(**_kwargs: Any) -> SideQuestionResult:
            raise AssertionError("no LLM call for an empty question")

        monkeypatch.setattr(handler, "ensure_agent", _ensure_agent)
        monkeypatch.setattr("klaude_code.agent.runtime.agent_ops.run_side_question", _fail_run)

        await handler.ask_side_question(op.AskSideQuestionOperation(session_id=session.id, question="   "))

        assert len(emitted) == 1
        assert isinstance(emitted[0], events.NoticeEvent)
        assert emitted[0].is_error is True
        assert not handler._side_question_tasks

    asyncio.run(_test())


def test_pending_side_question_is_cancelled_per_session(
    tmp_path: Path, isolated_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The task is not a runtime task, so session teardown must cancel it here."""
    del isolated_home

    async def _test() -> None:
        emitted: list[Any] = []

        async def _emit(event: Any) -> None:
            emitted.append(event)

        handler = _handler(_emit)
        session = Session(work_dir=tmp_path)
        released = asyncio.Event()

        async def _ensure_agent(_session_id: str) -> Any:
            return _fake_agent(session)

        async def _blocking_run(**_kwargs: Any) -> SideQuestionResult:
            await released.wait()
            raise AssertionError("cancelled before this point")

        monkeypatch.setattr(handler, "ensure_agent", _ensure_agent)
        monkeypatch.setattr("klaude_code.agent.runtime.agent_ops.run_side_question", _blocking_run)

        operation = op.AskSideQuestionOperation(session_id=session.id, question="why?")
        await handler.ask_side_question(operation)
        assert operation.id in handler._side_question_tasks

        handler.cancel_side_questions("other-session")
        assert operation.id in handler._side_question_tasks

        handler.cancel_side_questions(session.id)
        await asyncio.sleep(0)
        assert not handler._side_question_tasks
        assert not any(isinstance(item, message.SideQuestionEntry) for item in session.conversation_history)
        assert not any(isinstance(event, events.SideQuestionFailedEvent) for event in emitted)

    asyncio.run(_test())


def test_side_question_failure_reports_and_clears_the_pending_request(
    tmp_path: Path, isolated_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    del isolated_home

    async def _test() -> None:
        emitted: list[Any] = []

        async def _emit(event: Any) -> None:
            emitted.append(event)

        handler = _handler(_emit)
        session = Session(work_dir=tmp_path)

        async def _ensure_agent(_session_id: str) -> Any:
            return _fake_agent(session)

        async def _failing_run(**_kwargs: Any) -> SideQuestionResult:
            raise SideQuestionError("529 overloaded")

        monkeypatch.setattr(handler, "ensure_agent", _ensure_agent)
        monkeypatch.setattr("klaude_code.agent.runtime.agent_ops.run_side_question", _failing_run)

        operation = op.AskSideQuestionOperation(session_id=session.id, question="why?")
        await handler.ask_side_question(operation)
        await _drain(handler)

        assert isinstance(emitted[-1], events.SideQuestionFailedEvent)
        assert emitted[-1].request_id == operation.id
        assert emitted[-1].error == "529 overloaded"
        assert not any(isinstance(item, message.SideQuestionEntry) for item in session.conversation_history)
        assert not handler._side_question_tasks

    asyncio.run(_test())
