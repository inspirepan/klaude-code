"""Characterization tests for compaction decision/scan helpers.

These lock in CURRENT observable behavior of:
- ``_resolve_compaction_config`` (threshold vs manual reason).
- ``should_compact_threshold`` decision edges not already covered.
- The backward-scan helpers (``_last_successful_usage_index``,
  ``_has_compaction_after_last_successful_usage``,
  ``_estimate_tokens_after_last_successful_usage``, ``get_last_context_tokens``,
  ``_find_last_compaction``).
- Pure collectors (``collect_messages``, ``collect_kept_items_brief``,
  ``estimate_history_tokens``).
- ``is_context_overflow`` (used to gate compaction-on-overflow in run()).

They assert what the code currently DOES, not what it should do, so a later
refactor can be proven behavior-preserving.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from klaude_code.agent.compaction import compaction
from klaude_code.agent.compaction.compaction import (
    CompactionConfig,
    CompactionReason,
    _resolve_compaction_config,
    collect_kept_items_brief,
    collect_messages,
    estimate_history_tokens,
    get_last_context_tokens,
    should_compact_threshold,
)
from klaude_code.agent.compaction.overflow import is_context_overflow
from klaude_code.protocol import llm_param, message
from klaude_code.protocol.models import Usage
from klaude_code.session.session import Session


def _cfg(*, context_limit: int | None = None, max_tokens: int | None = None) -> llm_param.LLMConfigParameter:
    return llm_param.LLMConfigParameter(
        protocol=llm_param.LLMClientProtocol.OPENAI,
        context_limit=context_limit,
        max_tokens=max_tokens,
    )


# ---------------------------------------------------------------------------
# _resolve_compaction_config golden values
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("context_limit", "reserve", "keep", "max_summary"),
    [
        # context_limit <= 0 -> defaults
        (0, 16384, 20000, 13107),
        (None, 16384, 20000, 13107),
        # Large limit hits the upper caps (16384 / 20000).
        (200000, 16384, 20000, 13107),
        (100000, 16384, 20000, 13107),
        # Small limit gets clamped by the inner max(2048, ...) / max(4096, ...).
        (4000, 2048, 1952, 1638),
        (8000, 2048, 4096, 1638),
        (30000, 7500, 10500, 6000),
    ],
)
def test_resolve_compaction_config_threshold(
    context_limit: int | None, reserve: int, keep: int, max_summary: int
) -> None:
    cfg = _resolve_compaction_config(_cfg(context_limit=context_limit))
    assert (cfg.reserve_tokens, cfg.keep_recent_tokens, cfg.max_summary_tokens) == (reserve, keep, max_summary)


@pytest.mark.parametrize(
    ("context_limit", "keep_recent"),
    [
        (0, 5000),
        (None, 5000),
        (200000, 5000),
        (100000, 5000),
        (4000, 1952),
        (8000, 2048),
        (30000, 2625),
    ],
)
def test_resolve_compaction_config_manual_shrinks_keep_recent(context_limit: int | None, keep_recent: int) -> None:
    cfg = _resolve_compaction_config(_cfg(context_limit=context_limit), reason=CompactionReason.MANUAL)
    assert cfg.keep_recent_tokens == keep_recent
    # reserve / max_summary are unchanged from the threshold computation.
    threshold = _resolve_compaction_config(_cfg(context_limit=context_limit))
    assert cfg.reserve_tokens == threshold.reserve_tokens
    assert cfg.max_summary_tokens == threshold.max_summary_tokens


# ---------------------------------------------------------------------------
# should_compact_threshold edges
# ---------------------------------------------------------------------------


def test_threshold_false_when_no_context_limit_anywhere(isolated_home: Path, tmp_path: Path) -> None:
    del isolated_home
    session = Session(id="no-limit", work_dir=tmp_path)
    session.conversation_history = [
        message.AssistantMessage(parts=[message.TextPart(text="hi")], usage=Usage(context_size=999_999)),
    ]
    result = should_compact_threshold(
        session=session,
        config=CompactionConfig(reserve_tokens=200, keep_recent_tokens=1000, max_summary_tokens=500),
        llm_config=_cfg(context_limit=None, max_tokens=0),
    )
    assert result is False


def test_threshold_false_when_effective_limit_non_positive(isolated_home: Path, tmp_path: Path) -> None:
    del isolated_home
    session = Session(id="effective-zero", work_dir=tmp_path)
    session.conversation_history = [
        message.AssistantMessage(
            parts=[message.TextPart(text="hi")],
            usage=Usage(context_size=10_000, context_limit=2_000),
        ),
    ]
    # max_tokens >= context_limit => effective_context_limit <= 0 => False.
    result = should_compact_threshold(
        session=session,
        config=CompactionConfig(reserve_tokens=100, keep_recent_tokens=1000, max_summary_tokens=500),
        llm_config=_cfg(context_limit=2_000, max_tokens=2_000),
    )
    assert result is False


def test_threshold_resolves_config_from_llm_config_when_none(isolated_home: Path, tmp_path: Path) -> None:
    del isolated_home
    session = Session(id="auto-config", work_dir=tmp_path)
    # context_size just over (effective_limit - reserve). For context_limit=200000,
    # max_tokens=32000 -> effective=168000; reserve resolved=16384 -> threshold=151616.
    session.conversation_history = [
        message.AssistantMessage(
            parts=[message.TextPart(text="ok")],
            usage=Usage(context_size=151_616, context_limit=200_000, max_tokens=32_000),
        ),
    ]
    result = should_compact_threshold(session=session, config=None, llm_config=_cfg(context_limit=200_000))
    assert result is True


def test_threshold_uses_session_context_limit_when_llm_config_missing(isolated_home: Path, tmp_path: Path) -> None:
    del isolated_home
    session = Session(id="session-limit-fallback", work_dir=tmp_path)
    session.conversation_history = [
        message.AssistantMessage(
            parts=[message.TextPart(text="ok")],
            usage=Usage(context_size=180_000, context_limit=200_000, max_tokens=32_000),
        ),
    ]
    # llm_config has no context_limit/max_tokens; they are read back from usage.
    result = should_compact_threshold(
        session=session,
        config=CompactionConfig(reserve_tokens=16_384, keep_recent_tokens=20_000, max_summary_tokens=13_107),
        llm_config=_cfg(context_limit=None, max_tokens=None),
    )
    assert result is True


# ---------------------------------------------------------------------------
# Backward-scan helpers
# ---------------------------------------------------------------------------


def test_last_successful_usage_index_skips_aborted_error_and_no_usage() -> None:
    history: list[message.HistoryEvent] = [
        message.AssistantMessage(parts=[message.TextPart(text="a")], usage=Usage(context_size=1)),  # 0 good
        message.AssistantMessage(parts=[message.TextPart(text="b")], usage=None),  # 1 no usage
        message.AssistantMessage(
            parts=[message.TextPart(text="c")], usage=Usage(context_size=2), stop_reason="aborted"
        ),  # 2 aborted
        message.AssistantMessage(
            parts=[message.TextPart(text="d")], usage=Usage(context_size=3), stop_reason="error"
        ),  # 3 error
    ]
    assert compaction._last_successful_usage_index(history) == 0  # pyright: ignore[reportPrivateUsage]


def test_last_successful_usage_index_none_when_no_usable_assistant() -> None:
    history: list[message.HistoryEvent] = [
        message.UserMessage(parts=[message.TextPart(text="hi")]),
        message.AssistantMessage(parts=[message.TextPart(text="x")], usage=None),
    ]
    assert compaction._last_successful_usage_index(history) is None  # pyright: ignore[reportPrivateUsage]


def test_has_compaction_after_last_successful_usage_true_when_compaction_newer(
    isolated_home: Path, tmp_path: Path
) -> None:
    del isolated_home
    session = Session(id="compaction-newer", work_dir=tmp_path)
    session.conversation_history = [
        message.AssistantMessage(parts=[message.TextPart(text="a")], usage=Usage(context_size=1)),
        message.CompactionEntry(summary="<summary>s</summary>", first_kept_index=1),
    ]
    assert compaction._has_compaction_after_last_successful_usage(session) is True  # pyright: ignore[reportPrivateUsage]


def test_has_compaction_after_last_successful_usage_false_when_usage_newer(isolated_home: Path, tmp_path: Path) -> None:
    del isolated_home
    session = Session(id="usage-newer", work_dir=tmp_path)
    session.conversation_history = [
        message.CompactionEntry(summary="<summary>s</summary>", first_kept_index=0),
        message.AssistantMessage(parts=[message.TextPart(text="a")], usage=Usage(context_size=1)),
    ]
    assert compaction._has_compaction_after_last_successful_usage(session) is False  # pyright: ignore[reportPrivateUsage]


def test_has_compaction_after_last_successful_usage_false_when_no_compaction(
    isolated_home: Path, tmp_path: Path
) -> None:
    del isolated_home
    session = Session(id="no-compaction", work_dir=tmp_path)
    session.conversation_history = [
        message.AssistantMessage(parts=[message.TextPart(text="a")], usage=Usage(context_size=1)),
    ]
    assert compaction._has_compaction_after_last_successful_usage(session) is False  # pyright: ignore[reportPrivateUsage]


def test_has_compaction_after_last_successful_usage_true_when_compaction_but_no_usage(
    isolated_home: Path, tmp_path: Path
) -> None:
    del isolated_home
    session = Session(id="compaction-no-usage", work_dir=tmp_path)
    session.conversation_history = [
        message.CompactionEntry(summary="<summary>s</summary>", first_kept_index=0),
        message.UserMessage(parts=[message.TextPart(text="hi")]),
    ]
    assert compaction._has_compaction_after_last_successful_usage(session) is True  # pyright: ignore[reportPrivateUsage]


def test_estimate_tokens_after_last_successful_usage_counts_only_trailing_messages(
    isolated_home: Path, tmp_path: Path
) -> None:
    del isolated_home
    session = Session(id="estimate-after", work_dir=tmp_path)
    session.conversation_history = [
        message.UserMessage(parts=[message.TextPart(text="x" * 100)]),  # before usage; ignored
        message.AssistantMessage(parts=[message.TextPart(text="ok")], usage=Usage(context_size=1)),
        message.ToolResultMessage(call_id="c1", tool_name="Bash", status="success", output_text="y" * 40),
    ]
    # Only the trailing ToolResultMessage (40 chars) counts: (40 + 3) // 4 == 10.
    assert compaction._estimate_tokens_after_last_successful_usage(session) == 10  # pyright: ignore[reportPrivateUsage]


def test_estimate_tokens_after_last_successful_usage_zero_when_no_usage(isolated_home: Path, tmp_path: Path) -> None:
    del isolated_home
    session = Session(id="estimate-no-usage", work_dir=tmp_path)
    session.conversation_history = [
        message.UserMessage(parts=[message.TextPart(text="x" * 100)]),
    ]
    assert compaction._estimate_tokens_after_last_successful_usage(session) == 0  # pyright: ignore[reportPrivateUsage]


# ---------------------------------------------------------------------------
# get_last_context_tokens
# ---------------------------------------------------------------------------


def test_get_last_context_tokens_prefers_context_size(isolated_home: Path, tmp_path: Path) -> None:
    del isolated_home
    session = Session(id="ctx-size", work_dir=tmp_path)
    session.conversation_history = [
        message.AssistantMessage(
            parts=[message.TextPart(text="a")],
            usage=Usage(context_size=1234),
        ),
    ]
    assert get_last_context_tokens(session) == 1234


def test_get_last_context_tokens_falls_back_to_total_tokens(isolated_home: Path, tmp_path: Path) -> None:
    del isolated_home
    session = Session(id="total-tokens", work_dir=tmp_path)
    # total_tokens is derived from input + output when context_size is unset.
    session.conversation_history = [
        message.AssistantMessage(
            parts=[message.TextPart(text="a")],
            usage=Usage(context_size=None, input_tokens=4000, output_tokens=321),
        ),
    ]
    assert get_last_context_tokens(session) == 4321


def test_get_last_context_tokens_skips_aborted_and_returns_none_when_absent(
    isolated_home: Path, tmp_path: Path
) -> None:
    del isolated_home
    session = Session(id="aborted-skip", work_dir=tmp_path)
    session.conversation_history = [
        message.AssistantMessage(
            parts=[message.TextPart(text="a")],
            usage=Usage(context_size=10),
            stop_reason="aborted",
        ),
        message.UserMessage(parts=[message.TextPart(text="hi")]),
    ]
    assert get_last_context_tokens(session) is None


# ---------------------------------------------------------------------------
# _find_last_compaction
# ---------------------------------------------------------------------------


def test_find_last_compaction_returns_newest() -> None:
    history: list[message.HistoryEvent] = [
        message.CompactionEntry(summary="first", first_kept_index=0),
        message.UserMessage(parts=[message.TextPart(text="hi")]),
        message.CompactionEntry(summary="second", first_kept_index=2),
    ]
    idx, entry = compaction._find_last_compaction(history)  # pyright: ignore[reportPrivateUsage]
    assert idx == 2
    assert entry is not None and entry.summary == "second"


def test_find_last_compaction_none_when_absent() -> None:
    history: list[message.HistoryEvent] = [message.UserMessage(parts=[message.TextPart(text="hi")])]
    idx, entry = compaction._find_last_compaction(history)  # pyright: ignore[reportPrivateUsage]
    assert idx == -1
    assert entry is None


# ---------------------------------------------------------------------------
# collect_messages
# ---------------------------------------------------------------------------


def test_collect_messages_filters_system_and_compaction_entries() -> None:
    history: list[message.HistoryEvent] = [
        message.SystemMessage(parts=[message.TextPart(text="sys")]),
        message.UserMessage(parts=[message.TextPart(text="u")]),
        message.CompactionEntry(summary="s", first_kept_index=0),
        message.AssistantMessage(parts=[message.TextPart(text="a")]),
    ]
    collected = collect_messages(history, 0, len(history))
    # SystemMessage excluded explicitly; CompactionEntry is not a Message.
    assert [type(m).__name__ for m in collected] == ["UserMessage", "AssistantMessage"]


def test_collect_messages_empty_when_end_before_start() -> None:
    history: list[message.HistoryEvent] = [message.UserMessage(parts=[message.TextPart(text="u")])]
    assert collect_messages(history, 5, 2) == []


# ---------------------------------------------------------------------------
# collect_kept_items_brief
# ---------------------------------------------------------------------------


def test_collect_kept_items_brief_groups_tools_and_previews() -> None:
    history: list[message.HistoryEvent] = [
        message.CompactionEntry(summary="s", first_kept_index=0),  # skipped
        message.UserMessage(parts=[message.TextPart(text="  please run the build now  ")]),
        message.ToolResultMessage(call_id="c1", tool_name="Bash", status="success", output_text="ok"),
        message.ToolResultMessage(call_id="c2", tool_name="Bash", status="success", output_text="ok"),
        message.AssistantMessage(parts=[message.TextPart(text="done building")]),
        message.AssistantMessage(parts=[message.TextPart(text="   ")]),  # blank -> skipped
    ]
    briefs = collect_kept_items_brief(history, cut_index=0)
    summary = [(b.item_type, b.count, b.preview) for b in briefs]
    # count defaults to 1 and preview defaults to "" on KeptItemBrief.
    assert summary == [
        ("User", 1, "please run the build now"),
        ("Bash", 2, ""),
        ("Assistant", 1, "done building"),
    ]


def test_collect_kept_items_brief_truncates_long_preview() -> None:
    history: list[message.HistoryEvent] = [
        message.UserMessage(parts=[message.TextPart(text="a" * 50)]),
    ]
    briefs = collect_kept_items_brief(history, cut_index=0)
    assert len(briefs) == 1
    assert briefs[0].preview == "a" * 30 + "..."


# ---------------------------------------------------------------------------
# estimate_history_tokens / token estimation
# ---------------------------------------------------------------------------


def test_estimate_history_tokens_ignores_non_message_entries() -> None:
    history: list[message.HistoryEvent] = [
        message.CompactionEntry(summary="s", first_kept_index=0),
        message.UserMessage(parts=[message.TextPart(text="x" * 40)]),  # (40+3)//4 = 10
        message.ToolResultMessage(call_id="c", tool_name="Bash", status="success", output_text="y" * 8),  # (8+3)//4=2
    ]
    assert estimate_history_tokens(history) == 12


def test_estimate_tokens_image_part_adds_fixed_cost() -> None:
    msg = message.UserMessage(parts=[message.ImageURLPart(url="http://example/x.png")])
    # No text chars -> only image cost (1200), divided: (1200+3)//4 = 300.
    assert compaction._estimate_tokens(msg) == 300  # pyright: ignore[reportPrivateUsage]


# ---------------------------------------------------------------------------
# is_context_overflow (gates compaction-on-overflow in run())
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("prompt is too long", True),
        ("This exceeds the context window", True),
        ("400 status code (no body)", True),
        ("429 (no body)", True),
        ("context length exceeded", True),
        ("input is too long", True),
        ("maximum context length is 8192 tokens", True),
        ("rate limit reached", False),
        ("insufficient_quota", False),
        ("", False),
        (None, False),
    ],
)
def test_is_context_overflow(text: str | None, expected: bool) -> None:
    assert is_context_overflow(text) is expected
