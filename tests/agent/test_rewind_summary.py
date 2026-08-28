# pyright: reportPrivateUsage=false

"""Tests for the user-facing `/rewind` flow (RewindWithSummaryOperation).

Covers the summary builder helpers and the AgentOperationHandler glue: pivot
validation, fork + ForkSummaryEntry append, ForkSummaryReadyEvent, and the
post-landing prompt suggestion. See agent/rewind/AGENTS.md for the two-rewind
vocabulary (this is the user rewind, not the model's `Rewind` tool).
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, cast

import pytest

from klaude_code.agent.agent_profile import AgentProfile
from klaude_code.agent.rewind.summary import (
    RewindSummaryResult,
    build_rewind_instruction,
    count_summarized_messages,
    run_rewind_summary,
)
from klaude_code.agent.runtime.agent_ops import AgentOperationHandler
from klaude_code.llm.client import LLMClientABC
from klaude_code.prompts.compaction import FORK_SUMMARY_PROMPT
from klaude_code.protocol import events, message, op
from klaude_code.protocol.models import Usage
from klaude_code.session.session import Session

# ---------------------------------------------------------------------------
# summary builder helpers (pure)
# ---------------------------------------------------------------------------


def _history() -> list[message.HistoryEvent]:
    return [
        message.UserMessage(parts=message.text_parts_from_str("A")),
        message.AssistantMessage(parts=message.text_parts_from_str("a reply")),
        message.UserMessage(parts=message.text_parts_from_str("B — the pivot")),
        message.UserMessage(parts=message.text_parts_from_str("C")),
    ]


def test_build_rewind_instruction_quotes_pivot() -> None:
    instruction = build_rewind_instruction(_history(), 2)
    text = message.join_text_parts(instruction.parts)
    assert isinstance(instruction, message.UserMessage)
    assert "B — the pivot" in text
    assert "C" not in text.split("</pivot-user-message>")[0]
    # The instruction is derived from the shared template.
    assert "Primary Request and Intent" in text


def test_build_rewind_instruction_entire_conversation() -> None:
    instruction = build_rewind_instruction(_history(), -1)
    text = message.join_text_parts(instruction.parts)
    assert "(session start)" in text


def test_count_summarized_messages() -> None:
    history = _history()
    assert count_summarized_messages(history, 2) == 2
    assert count_summarized_messages(history, -1) == 4
    # A ForkSummaryEntry projects into the LLM view and counts as one message.
    history.append(
        message.ForkSummaryEntry(summary="x", source_session_id="s", source_pivot_index=0, source_message_count=0)
    )
    assert count_summarized_messages(history, -1) == 5


def test_prompt_template_has_pivot_token_replaced() -> None:
    prompt = FORK_SUMMARY_PROMPT.replace("__PIVOT_MESSAGE__", "pivot quote").replace("__SCOPE_NOTE__", "scope")
    assert "__PIVOT_MESSAGE__" not in prompt
    assert "__SCOPE_NOTE__" not in prompt


# ---------------------------------------------------------------------------
# run_rewind_summary (monkeypatched LLM client)
# ---------------------------------------------------------------------------


class _FakeLLMClient:
    def __init__(self, text: str, usage: Usage | None) -> None:
        self.text = text
        self.usage = usage
        self.calls: list[Any] = []
        self._cfg = type("Cfg", (), {"model_id": "m", "provider_name": "p", "thinking": None})()

    async def call(self, call_param: Any):
        self.calls.append(call_param)

        async def _stream():
            yield message.AssistantMessage(
                parts=message.text_parts_from_str(self.text),
                usage=self.usage,
            )

        return _stream()

    def get_llm_config(self) -> Any:
        return self._cfg


def _sharable_profile() -> Any:
    """A fake profile whose client config matches _FakeLLMClient's."""

    cfg = type("Cfg", (), {"model_id": "m", "provider_name": "p", "thinking": None})()
    return type(
        "Profile",
        (),
        {
            "llm_client": type("C", (), {"get_llm_config": staticmethod(lambda: cfg)})(),
            "system_prompt": "sys",
            "tools": [],
        },
    )()


def test_run_rewind_summary_fork_path_captures_usage(tmp_path: Path, isolated_home: Path) -> None:
    del isolated_home

    async def _test() -> None:
        session = Session(work_dir=tmp_path)
        session.append_history(_history())

        client = _FakeLLMClient(
            "summary body",
            usage=Usage(input_tokens=1000, cached_tokens=900, cache_write_tokens=0),
        )
        result = await run_rewind_summary(
            session=session,
            active_view=_history(),
            pivot_index=2,
            llm_client=cast(LLMClientABC, client),
            main_profile=cast(AgentProfile, _sharable_profile()),
            tokens_before=5000,
        )

        assert result.text == "summary body"
        assert result.message_count == 2
        assert result.tokens_before == 5000
        assert result.cache_hit_rate == pytest.approx(0.9)
        assert result.fallback_used is False
        # Fork path: full history prefix + trailing instruction, main-profile wire.
        assert len(client.calls) == 1
        input_messages = client.calls[0].input
        assert isinstance(input_messages[-1], message.UserMessage)
        assert "B — the pivot" in message.join_text_parts(input_messages[-1].parts)
        assert client.calls[0].max_tokens is not None

    asyncio.run(_test())


def test_run_rewind_summary_fallback_serializes_tail(
    tmp_path: Path, isolated_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    del isolated_home

    async def _test() -> None:
        session = Session(work_dir=tmp_path)
        session.append_history(_history())

        client = _FakeLLMClient("fallback body", usage=None)
        # A main profile whose client config differs -> not cache sharable.
        main_client_cfg = type("Cfg", (), {"model_id": "other", "provider_name": "other", "thinking": None})()
        profile = type(
            "Profile",
            (),
            {"llm_client": type("C", (), {"get_llm_config": staticmethod(lambda: main_client_cfg)})()},
        )()

        result = await run_rewind_summary(
            session=session,
            active_view=_history(),
            pivot_index=2,
            llm_client=cast(LLMClientABC, client),
            main_profile=cast(AgentProfile, profile),
            tokens_before=None,
        )

        assert result.text == "fallback body"
        assert result.fallback_used is True
        assert result.cache_hit_rate is None
        # Fallback path: one standalone request with the serialized tail inline.
        input_messages = client.calls[0].input
        first = message.join_text_parts(input_messages[0].parts)
        assert "<conversation>" in first
        assert "C" in first

    asyncio.run(_test())


# ---------------------------------------------------------------------------
# AgentOperationHandler glue
# ---------------------------------------------------------------------------


def _handler(emit: Any, spawned: list[asyncio.Task[None]]) -> AgentOperationHandler:
    handler = object.__new__(AgentOperationHandler)
    handler._emit_event = emit
    handler._prompt_suggestion_tasks = {}

    def _register_task(*, task: asyncio.Task[None], **_kwargs: Any) -> None:
        spawned.append(task)

    handler._register_task = _register_task  # type: ignore[method-assign]
    handler._remove_task = lambda **_kwargs: None  # type: ignore[method-assign]
    return handler


async def _drain_tasks(spawned: list[asyncio.Task[None]], handler: AgentOperationHandler) -> None:
    for task in list(spawned):
        await task
    for pending in list(handler._prompt_suggestion_tasks.values()):
        await pending


def test_rewind_op_forks_appends_entry_and_emits_ready(
    tmp_path: Path, isolated_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    del isolated_home

    async def _test() -> None:
        emitted: list[Any] = []

        async def _emit(event: Any) -> None:
            emitted.append(event)

        spawned: list[asyncio.Task[None]] = []
        handler = _handler(_emit, spawned)
        session = Session.create(work_dir=tmp_path)
        session.append_history(_history())
        await session.wait_for_flush()

        sessions_by_id: dict[str, Session] = {session.id: session}

        def _fake_agent(target: Session) -> Any:
            return type(
                "FakeAgent",
                (),
                {"session": target, "profile": object(), "follow_up_count": staticmethod(lambda: 0)},
            )()

        async def _ensure_agent(_session_id: str, **_kwargs: Any) -> Any:
            # Mirror the real handler: the new session resolves through a
            # fresh load so the suggestion lands on the live object.
            target = sessions_by_id.get(_session_id)
            if target is None:
                target = Session.load(_session_id, work_dir=session.work_dir)
                sessions_by_id[_session_id] = target
            return _fake_agent(target)

        def _fake_clients(_session_id: str) -> Any:
            return type("FakeClients", (), {"get_compact_client": staticmethod(lambda: object())})()

        async def _fake_summary(**_kwargs: Any) -> RewindSummaryResult:
            return RewindSummaryResult(
                text="SUMMARY BODY",
                message_count=2,
                tokens_before=123,
                cache_hit_rate=0.5,
                fallback_used=False,
            )

        async def _fake_suggestion(**_kwargs: Any) -> Any:
            return type("R", (), {"suggestion": "continue the rewound work", "raw": "", "drop_reason": None})()

        monkeypatch.setattr(handler, "ensure_agent", _ensure_agent)
        monkeypatch.setattr(handler, "get_session_llm_clients", _fake_clients)
        monkeypatch.setattr("klaude_code.agent.runtime.agent_ops.run_rewind_summary", _fake_summary)
        monkeypatch.setattr("klaude_code.agent.runtime.agent_ops.run_prompt_suggestion", _fake_suggestion)

        operation = op.RewindWithSummaryOperation(session_id=session.id, pivot_index=2, pivot_text="B — the pivot")
        await handler.rewind_with_summary(operation)
        await _drain_tasks(spawned, handler)

        ready = [e for e in emitted if isinstance(e, events.ForkSummaryReadyEvent)]
        assert len(ready) == 1
        assert ready[0].operation_id == operation.id
        assert ready[0].new_session_id != session.id

        loaded = Session.load(ready[0].new_session_id, work_dir=session.work_dir)
        entries = [item for item in loaded.conversation_history if isinstance(item, message.ForkSummaryEntry)]
        assert len(entries) == 1
        assert entries[0].summary == "SUMMARY BODY"
        assert entries[0].source_pivot_index == 2
        # LLM view: kept prefix + summary as UserMessage. Sidecar entries
        # (PromptSuggestionEntry) may appear in get_llm_history output —
        # wire-building call sites filter to Messages — but must never leak
        # into the model-facing view.
        llm_history = loaded.get_llm_history()
        wire = [m for m in llm_history if isinstance(m, message.Message)]
        assert isinstance(wire[-1], message.UserMessage)
        assert "SUMMARY BODY" in message.join_text_parts(wire[-1].parts)
        assert all("continue the rewound work" not in message.join_text_parts(m.parts) for m in wire)
        # Suggested prompt landed after the summary entry.
        suggestions = [item for item in loaded.conversation_history if isinstance(item, message.PromptSuggestionEntry)]
        assert len(suggestions) == 1
        assert suggestions[0].text == "continue the rewound work"

    asyncio.run(_test())


def test_rewind_op_rejects_non_user_pivot(tmp_path: Path, isolated_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    del isolated_home

    async def _test() -> None:
        emitted: list[Any] = []

        async def _emit(event: Any) -> None:
            emitted.append(event)

        spawned: list[asyncio.Task[None]] = []
        handler = _handler(_emit, spawned)
        session = Session(work_dir=tmp_path)
        session.append_history(_history())

        async def _ensure_agent(_session_id: str, **_kwargs: Any) -> Any:
            return type(
                "FakeAgent",
                (),
                {"session": session, "profile": object(), "follow_up_count": staticmethod(lambda: 0)},
            )()

        monkeypatch.setattr(handler, "ensure_agent", _ensure_agent)

        # Index 1 is an AssistantMessage — not a valid pivot.
        operation = op.RewindWithSummaryOperation(session_id=session.id, pivot_index=1)
        await handler.rewind_with_summary(operation)
        await _drain_tasks(spawned, handler)

        notices = [e for e in emitted if isinstance(e, events.NoticeEvent)]
        assert len(notices) == 1
        assert notices[0].is_error is True
        assert not [e for e in emitted if isinstance(e, events.ForkSummaryReadyEvent)]

    asyncio.run(_test())
