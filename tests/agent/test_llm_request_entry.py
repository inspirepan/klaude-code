"""`LLMRequestEntry`: persistence, model-invisibility, and the three call sites.

The entry is the viewer's request dot for the LLM calls that happen outside a
step. Two properties matter and are pinned here:

1. It round-trips through the session codec and is classified ``sidecar``.
2. It never reaches the model — not through ``get_llm_history()``, not through
   the step's own input filter.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any, cast

import pytest

from klaude_code.agent.agent_profile import AgentProfile
from klaude_code.agent.compaction.compaction import CompactionReason, run_compaction
from klaude_code.agent.llm_request import LLMRequestLog, safe_call_options
from klaude_code.agent.rewind.summary import run_rewind_summary
from klaude_code.agent.side_question import SideQuestionError, run_side_question
from klaude_code.agent.step import LLM_INPUT_MESSAGE_TYPES
from klaude_code.llm.client import LLMClientABC, LLMStreamABC
from klaude_code.protocol import llm_param, message
from klaude_code.protocol.models import Usage
from klaude_code.session.codec import decode_jsonl_line, encode_jsonl_line
from klaude_code.session.history import scan_history
from klaude_code.session.session import Session


@pytest.fixture(autouse=True)
def _isolate_home(isolated_home: Path) -> Path:  # pyright: ignore[reportUnusedFunction]
    return isolated_home


# ---------------------------------------------------------------------------
# doubles
# ---------------------------------------------------------------------------


class _ScriptedStream(LLMStreamABC):
    def __init__(self, items: list[message.LLMStreamItem]) -> None:
        self._items = items

    def __aiter__(self) -> AsyncGenerator[message.LLMStreamItem]:
        return self._iterate()

    async def _iterate(self) -> AsyncGenerator[message.LLMStreamItem]:
        for item in self._items:
            yield item

    def get_partial_message(self) -> message.AssistantMessage | None:
        return None


class _ScriptedClient(LLMClientABC):
    """Replies with a scripted stream per call, or raises what it was given."""

    def __init__(self, *responses: list[message.LLMStreamItem] | Exception, api_key: str = "sk-SECRET") -> None:
        super().__init__(
            llm_param.LLMConfigParameter(
                provider_name="test-provider",
                protocol=llm_param.LLMClientProtocol.OPENAI,
                model_id="fake-model",
                api_key=api_key,
                temperature=0.25,
                effort="high",
                max_tokens=4096,
                context_limit=6000,
            )
        )
        self._responses = list(responses)
        self.calls: list[llm_param.LLMCallParameter] = []

    @classmethod
    def create(cls, config: llm_param.LLMConfigParameter) -> LLMClientABC:
        del config
        raise NotImplementedError

    async def call(self, param: llm_param.LLMCallParameter) -> LLMStreamABC:
        self.calls.append(param)
        response = self._responses.pop(0) if self._responses else []
        if isinstance(response, Exception):
            raise response
        # Providers fill call defaults in place; mimic that so `options` shows
        # the effective config the way it does in production.
        if param.model_id is None:
            param.model_id = self.get_llm_config().model_id
        if param.temperature is None:
            param.temperature = self.get_llm_config().temperature
        return _ScriptedStream(response)


def _answer(text: str, usage: Usage | None = None) -> list[message.LLMStreamItem]:
    return [
        message.AssistantTextDelta(content=text),
        message.AssistantMessage(parts=message.text_parts_from_str(text), usage=usage),
    ]


def _profile(client: LLMClientABC) -> AgentProfile:
    return AgentProfile(
        llm_client=client,
        system_prompt="MAIN SYSTEM PROMPT",
        tools=[llm_param.ToolSchema(name="Read", type="function", description="read", parameters={})],
        attachments=[],
    )


def _usage() -> Usage:
    return Usage(input_tokens=1000, cached_tokens=900, cache_write_tokens=0, output_tokens=42)


# ---------------------------------------------------------------------------
# schema / codec / ledger classification
# ---------------------------------------------------------------------------


def test_entry_round_trips_through_the_session_codec() -> None:
    entry = message.LLMRequestEntry(
        kind="side_question",
        label="fork",
        provider="test-provider",
        model="fake-model",
        options={"max_tokens": 4096, "effort": "high"},
        status="error",
        error="boom",
        usage=_usage(),
        tool_call_count=2,
    )

    decoded = decode_jsonl_line(encode_jsonl_line(entry))

    assert isinstance(decoded, message.LLMRequestEntry)
    assert decoded.model_dump(mode="json") == entry.model_dump(mode="json")


def test_entry_scans_as_a_sidecar_line() -> None:
    rows: list[tuple[int, message.HistoryEvent | None]] = [
        (0, message.LLMRequestEntry(kind="compaction")),
        (1, message.CompactionEntry(summary="s", first_kept_index=0)),
    ]

    statuses = scan_history(rows).statuses

    assert statuses[0].status == "sidecar"
    assert statuses[1].status == "active"


def test_entry_never_reaches_the_model(tmp_path: Path) -> None:
    session = Session(work_dir=tmp_path)
    session.conversation_history = [
        message.UserMessage(parts=message.text_parts_from_str("hi")),
        message.LLMRequestEntry(kind="side_question"),
        message.SideQuestionEntry(question="q", answer="a"),
        message.AssistantMessage(parts=message.text_parts_from_str("hello")),
    ]

    llm_history = session.get_llm_history()
    # The real step filter, not a copy of it. Sidecars survive get_llm_history()
    # (SideQuestionEntry does too); the Message filter is what stops them, and
    # every call site that builds an LLMCallParameter applies it.
    wire = [item for item in llm_history if isinstance(item, LLM_INPUT_MESSAGE_TYPES)]
    wire_via_message = [item for item in llm_history if isinstance(item, message.Message)]

    assert any(isinstance(item, message.LLMRequestEntry) for item in session.conversation_history)
    assert not any(isinstance(item, message.LLMRequestEntry) for item in wire)
    assert not any(isinstance(item, message.LLMRequestEntry) for item in wire_via_message)
    assert message.LLMRequestEntry not in LLM_INPUT_MESSAGE_TYPES
    assert [type(item).__name__ for item in wire] == ["UserMessage", "AssistantMessage"]


def test_safe_call_options_drops_the_payload_and_any_credential() -> None:
    param = llm_param.LLMCallParameter(input=[], system="SYS", session_id="s", prompt_cache_key="k")
    param.tools = [llm_param.ToolSchema(name="Read", type="function", description="d", parameters={})]
    param.max_tokens = 4096
    param.effort = "high"
    # A credential field is not on LLMCallParameter, but the exclusion set is
    # shared with the config dump, so a future move of the field stays covered.
    options = safe_call_options(param)

    assert options == {"max_tokens": 4096, "effort": "high", "fast_mode": False, "supports_vision": True}
    for banned in ("input", "system", "tools", "session_id", "prompt_cache_key", *llm_param.LLM_CONFIG_SECRET_FIELDS):
        assert banned not in options


# ---------------------------------------------------------------------------
# call site: /btw side question
# ---------------------------------------------------------------------------


def _session_with_history(tmp_path: Path) -> Session:
    session = Session(work_dir=tmp_path)
    session.conversation_history = [
        message.UserMessage(parts=message.text_parts_from_str("implement the parser")),
        message.AssistantMessage(parts=message.text_parts_from_str("done")),
    ]
    return session


def test_side_question_records_a_completed_request(tmp_path: Path) -> None:
    client = _ScriptedClient(_answer("because X", _usage()))
    session = _session_with_history(tmp_path)
    log = LLMRequestLog()

    result = asyncio.run(
        run_side_question(session=session, main_profile=_profile(client), question="why?", request_log=log)
    )

    assert [entry.request_id for entry in log.entries] == [result.request_id]
    entry = log.entries[0]
    assert entry.kind == "side_question"
    assert entry.status == "completed"
    assert entry.provider == "test-provider"
    assert entry.model == "fake-model"
    assert entry.usage is not None and entry.usage.input_tokens == 1000
    assert entry.first_token_at is not None
    assert entry.completed_at is not None
    assert entry.started_at <= entry.first_token_at <= entry.completed_at
    assert entry.options is not None and "api_key" not in entry.options


def test_side_question_records_a_failed_request(tmp_path: Path) -> None:
    client = _ScriptedClient([message.StreamErrorItem(error="upstream 500")])
    session = _session_with_history(tmp_path)
    log = LLMRequestLog()

    with pytest.raises(SideQuestionError):
        asyncio.run(run_side_question(session=session, main_profile=_profile(client), question="why?", request_log=log))

    assert len(log.entries) == 1
    assert log.entries[0].status == "error"
    assert log.entries[0].error == "upstream 500"


# ---------------------------------------------------------------------------
# call site: compaction
# ---------------------------------------------------------------------------


def _compactable_session(tmp_path: Path) -> Session:
    session = Session(work_dir=tmp_path)
    session.conversation_history = [
        message.UserMessage(parts=message.text_parts_from_str("old task " + "u" * 10_000)),
        message.AssistantMessage(parts=message.text_parts_from_str("old answer")),
        message.UserMessage(parts=message.text_parts_from_str("recent task " + "r" * 10_000)),
        message.AssistantMessage(parts=message.text_parts_from_str("tail")),
    ]
    return session


def test_compaction_fork_path_records_the_request_and_links_the_entry(tmp_path: Path) -> None:
    client = _ScriptedClient(_answer("SUMMARY", _usage()))
    session = _compactable_session(tmp_path)
    log = LLMRequestLog()

    result = asyncio.run(
        run_compaction(
            session=session,
            reason=CompactionReason.MANUAL,
            focus=None,
            llm_client=client,
            llm_config=client.get_llm_config(),
            main_profile=_profile(client),
            request_log=log,
        )
    )

    assert [entry.label for entry in log.entries] == ["fork"]
    entry = log.entries[0]
    assert entry.kind == "compaction"
    assert entry.status == "completed"
    assert result.request_id == entry.request_id
    assert result.usage is not None
    assert result.to_entry().request_id == entry.request_id


def test_compaction_summarizer_path_records_the_request(tmp_path: Path) -> None:
    # A summarizer client whose config differs from the main profile is not
    # cache-sharable, which is what selects the plain summarizer path.
    summarizer = _ScriptedClient(_answer("SUMMARY", _usage()))
    main_client = _ScriptedClient()
    main_client.get_llm_config().model_id = "other-model"
    session = _compactable_session(tmp_path)
    log = LLMRequestLog()

    result = asyncio.run(
        run_compaction(
            session=session,
            reason=CompactionReason.MANUAL,
            focus=None,
            llm_client=summarizer,
            llm_config=summarizer.get_llm_config(),
            main_profile=_profile(main_client),
            request_log=log,
        )
    )

    assert [entry.label for entry in log.entries] == ["summary"]
    assert log.entries[0].kind == "compaction"
    assert result.request_id == log.entries[0].request_id


def test_compaction_records_the_request_that_failed(tmp_path: Path) -> None:
    client = _ScriptedClient([message.StreamErrorItem(error="context length")])
    session = _compactable_session(tmp_path)
    log = LLMRequestLog()

    with pytest.raises(RuntimeError):
        asyncio.run(
            run_compaction(
                session=session,
                reason=CompactionReason.MANUAL,
                focus=None,
                llm_client=client,
                llm_config=client.get_llm_config(),
                main_profile=_profile(client),
                request_log=log,
            )
        )

    assert len(log.entries) == 1
    assert log.entries[0].status == "error"
    assert log.entries[0].error == "context length"


# ---------------------------------------------------------------------------
# call site: /rewind fork summary
# ---------------------------------------------------------------------------


def test_rewind_summary_records_the_request_and_links_the_entry(tmp_path: Path) -> None:
    client = _ScriptedClient(_answer("FORK SUMMARY", _usage()))
    session = Session(work_dir=tmp_path)
    history: list[message.HistoryEvent] = [
        message.UserMessage(parts=message.text_parts_from_str("A")),
        message.AssistantMessage(parts=message.text_parts_from_str("a")),
        message.UserMessage(parts=message.text_parts_from_str("B")),
    ]
    session.conversation_history = list(history)
    log = LLMRequestLog()

    result = asyncio.run(
        run_rewind_summary(
            session=session,
            active_view=list(history),
            pivot_index=2,
            llm_client=client,
            main_profile=_profile(client),
            tokens_before=5000,
            request_log=log,
        )
    )

    assert [entry.kind for entry in log.entries] == ["fork"]
    assert log.entries[0].label == "fork"
    assert result.request_id == log.entries[0].request_id
    assert result.usage is not None and result.usage.input_tokens == 1000

    fork_entry = message.ForkSummaryEntry(
        summary=result.text,
        source_session_id=session.id,
        source_pivot_index=2,
        source_message_count=result.message_count,
        request_id=result.request_id,
    )
    assert fork_entry.request_id == log.entries[0].request_id


def test_timing_fields_are_null_when_nothing_streamed(tmp_path: Path) -> None:
    # No deltas and no final message: the call still records, with no TTFT.
    client = _ScriptedClient(RuntimeError("connection reset"))
    session = _session_with_history(tmp_path)
    log = LLMRequestLog()

    with pytest.raises(SideQuestionError):
        asyncio.run(run_side_question(session=session, main_profile=_profile(client), question="why?", request_log=log))

    entry = log.entries[0]
    assert entry.first_token_at is None
    assert entry.usage is None
    assert entry.completed_at is not None
    assert entry.status == "error"


def test_ordered_entries_sorts_concurrent_calls_by_start(tmp_path: Path) -> None:
    del tmp_path
    log = LLMRequestLog()
    late = message.LLMRequestEntry(kind="compaction", label="task_prefix")
    early = message.LLMRequestEntry(kind="compaction", label="summary")
    early.started_at = late.started_at.replace(microsecond=0)
    log.entries.extend([late, early])

    assert [entry.label for entry in log.ordered_entries] == ["summary", "task_prefix"]
    assert log.primary_request_id == early.request_id
    assert cast(Any, log.find("task_prefix")).request_id == late.request_id
