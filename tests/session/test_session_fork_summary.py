from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from pathlib import Path
from typing import Any

from klaude_code.agent.compaction.compaction import estimate_history_tokens
from klaude_code.prompts.compaction import FORK_SUMMARY_USER_PREFIX
from klaude_code.protocol import events, message
from klaude_code.session.session import Session


def arun[T](coro: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(coro)


def _fork_entry() -> message.ForkSummaryEntry:
    return message.ForkSummaryEntry(
        summary="## Progress\n- [x] wrote the rewind feature",
        source_session_id="source-session",
        source_pivot_index=1,
        source_message_count=3,
        tokens_before=4200,
        cache_hit_rate=0.91,
    )


def _user(text: str) -> message.UserMessage:
    return message.UserMessage(parts=message.text_parts_from_str(text))


def _text(item: message.HistoryEvent) -> str | None:
    if isinstance(item, message.UserMessage | message.AssistantMessage | message.DeveloperMessage):
        return message.join_text_parts(item.parts)
    return None


def test_get_llm_history_translates_fork_summary_to_user_message(tmp_path: Path, isolated_home: Path) -> None:
    del isolated_home  # fixture only needed for its side effects

    async def _test() -> None:
        session = Session(work_dir=tmp_path)
        session.append_history([_user("first request")])
        session.append_history([_fork_entry()])

        llm_history = session.get_llm_history()

        assert [type(item).__name__ for item in llm_history] == ["UserMessage", "UserMessage"]
        summary_text = _text(llm_history[1])
        assert summary_text is not None
        assert summary_text.startswith(FORK_SUMMARY_USER_PREFIX)
        assert "rewind feature" in summary_text

    asyncio.run(_test())


def test_fork_summary_before_compaction_is_covered_by_compaction_summary(tmp_path: Path, isolated_home: Path) -> None:
    del isolated_home

    async def _test() -> None:
        session = Session(work_dir=tmp_path)
        session.append_history([_user("first request")])
        session.append_history([_fork_entry()])
        session.append_history([message.CompactionEntry(summary="compact summary", first_kept_index=2)])

        llm_history = session.get_llm_history()

        # The compaction boundary swallows the fork summary: its kept suffix
        # starts at first_kept_index, past the entry.
        assert [type(item).__name__ for item in llm_history] == ["UserMessage"]
        assert _text(llm_history[0]) == "compact summary"

    asyncio.run(_test())


def test_rebuild_keeps_fork_summary_in_active_history(tmp_path: Path, isolated_home: Path) -> None:
    del isolated_home

    project_dir = tmp_path / "project"
    project_dir.mkdir()

    async def _test() -> None:
        session = Session.create(work_dir=project_dir)
        session.append_history([_user("first request")])
        session.append_history([_fork_entry()])
        await session.wait_for_flush()

        loaded = Session.load(session.id, work_dir=project_dir)

        assert [type(item).__name__ for item in loaded.conversation_history] == [
            "UserMessage",
            "ForkSummaryEntry",
        ]
        llm_history = loaded.get_llm_history()
        summary_text = _text(llm_history[1])
        assert summary_text is not None
        assert summary_text.startswith(FORK_SUMMARY_USER_PREFIX)

    asyncio.run(_test())


def test_get_history_item_yields_fork_summary_event(tmp_path: Path, isolated_home: Path) -> None:
    del isolated_home

    async def _test() -> None:
        session = Session(work_dir=tmp_path)
        session.append_history([_user("first request")])
        session.append_history([_fork_entry()])

        replay_events = list(session.get_history_item())
        fork_events = [e for e in replay_events if isinstance(e, events.ForkSummaryEvent)]

        assert len(fork_events) == 1
        assert fork_events[0].summary.startswith("## Progress")
        assert fork_events[0].source_message_count == 3
        assert fork_events[0].tokens_before == 4200
        assert fork_events[0].cache_hit_rate == 0.91

    asyncio.run(_test())


def test_estimate_history_tokens_counts_fork_summary(tmp_path: Path, isolated_home: Path) -> None:
    del isolated_home

    entry = _fork_entry()
    bare = estimate_history_tokens([_user("first request")])
    with_entry = estimate_history_tokens([_user("first request"), entry])

    assert with_entry > bare
    expected = (len(FORK_SUMMARY_USER_PREFIX) + len(entry.summary) + 3) // 4
    assert with_entry - bare == expected
