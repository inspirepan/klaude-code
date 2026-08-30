"""Unit tests for the shared raw-line scan (`session/history.py`).

The scan is the single implementation behind both the loader's active list and
the (future) ledger view, so these tests pin per-line statuses as well as the
rebuilt list. No session store is touched: the scan works on plain rows.
"""

from __future__ import annotations

from collections.abc import Sequence

from klaude_code.protocol import message
from klaude_code.protocol.models import TaskMetadataItem
from klaude_code.session.history import LineStatus, rebuild_loaded_history, scan_history


def _rows(*items: message.HistoryEvent | None) -> list[tuple[int, message.HistoryEvent | None]]:
    return list(enumerate(items))


def _user(text: str) -> message.UserMessage:
    return message.UserMessage(parts=message.text_parts_from_str(text))


def _assistant(text: str) -> message.AssistantMessage:
    return message.AssistantMessage(parts=message.text_parts_from_str(text))


def _statuses(result_statuses: Sequence[LineStatus]) -> list[tuple[int, str, int | None]]:
    return [(s.line_index, s.status, s.dropped_by) for s in result_statuses]


def test_scan_keeps_every_line_index_and_marks_plain_lines_active() -> None:
    scan = scan_history(_rows(_user("hi"), _assistant("hello")))

    assert [type(item).__name__ for item in scan.active] == ["UserMessage", "AssistantMessage"]
    assert scan.active_lines == [0, 1]
    assert _statuses(scan.statuses) == [(0, "active", None), (1, "active", None)]
    assert scan.first_kept_active_index is None


def test_scan_reports_undecodable_lines_as_unknown_without_shifting_indices() -> None:
    scan = scan_history(_rows(_user("hi"), None, _assistant("hello")))

    assert scan.active_lines == [0, 2]
    assert _statuses(scan.statuses) == [(0, "active", None), (1, "unknown", None), (2, "active", None)]


def test_scan_tags_sidecar_entries_but_keeps_them_in_the_active_list() -> None:
    sidecars: list[message.HistoryEvent] = [
        message.CacheHitRateEntry(cache_hit_rate=0.5, cached_tokens=1, prev_step_input_tokens=2),
        TaskMetadataItem(),
        message.SideQuestionEntry(question="q", answer="a"),
        message.SpawnSubAgentEntry(session_id="s", sub_agent_type="t", sub_agent_desc="d"),
        message.InterruptEntry(),
        message.StreamErrorItem(error="boom"),
        message.AwaySummaryEntry(text="recap"),
        message.PromptSuggestionEntry(text="next"),
        message.TaskFileChangeSummaryEntry(),
        message.FallbackModelConfigWarnEntry(from_model="a", to_model="b", reason="r"),
        message.LLMRequestEntry(kind="compaction"),
    ]
    scan = scan_history(_rows(*sidecars))

    assert len(scan.active) == len(sidecars)
    assert {s.status for s in scan.statuses} == {"sidecar"}


def test_scan_drops_the_retracted_message_by_line() -> None:
    scan = scan_history(
        _rows(
            _user("keep"),
            _user("drop"),
            message.RetractEntry(retracted_text="drop", retracted_line=1),
        )
    )

    assert [message.join_text_parts(item.parts) for item in scan.active if isinstance(item, message.UserMessage)] == [
        "keep"
    ]
    assert scan.active_lines == [0, 2]
    assert _statuses(scan.statuses) == [(0, "active", None), (1, "retracted", 2), (2, "active", None)]


def test_scan_falls_back_to_the_text_anchor_when_no_line_is_recorded() -> None:
    scan = scan_history(
        _rows(
            _user("keep"),
            _user("drop"),
            message.RetractEntry(retracted_text="drop"),
        )
    )

    assert scan.active_lines == [0, 2]
    assert _statuses(scan.statuses)[1] == (1, "retracted", 2)


def test_scan_falls_back_to_text_when_the_recorded_line_is_not_a_live_user_message() -> None:
    # A stale line (points at the assistant reply) must not lose the wrong item.
    scan = scan_history(
        _rows(
            _user("keep"),
            _assistant("reply"),
            _user("drop"),
            message.RetractEntry(retracted_text="drop", retracted_line=1),
        )
    )

    assert scan.active_lines == [0, 1, 3]
    assert _statuses(scan.statuses)[2] == (2, "retracted", 3)


def test_scan_leaves_history_untouched_on_a_drifted_retract_anchor() -> None:
    scan = scan_history(_rows(_user("kept"), message.RetractEntry(retracted_text="never sent")))

    assert scan.active_lines == [0, 1]
    assert _statuses(scan.statuses) == [(0, "active", None), (1, "active", None)]


def test_scan_marks_the_compacted_prefix_by_line_without_removing_it() -> None:
    scan = scan_history(
        _rows(
            _user("old"),
            _assistant("old reply"),
            _user("kept"),
            message.CompactionEntry(summary="s", first_kept_index=999, first_kept_line=2),
        )
    )

    # Nothing is cut: the file line wins over the (deliberately wrong) index.
    assert scan.active_lines == [0, 1, 2, 3]
    assert _statuses(scan.statuses) == [
        (0, "compacted", 3),
        (1, "compacted", 3),
        (2, "active", None),
        (3, "active", None),
    ]
    assert scan.first_kept_active_index == 2


def test_scan_falls_back_to_the_compaction_index_for_old_entries() -> None:
    scan = scan_history(
        _rows(
            _user("old"),
            _assistant("old reply"),
            _user("kept"),
            message.CompactionEntry(summary="s", first_kept_index=2),
        )
    )

    assert _statuses(scan.statuses)[:3] == [(0, "compacted", 3), (1, "compacted", 3), (2, "active", None)]
    assert scan.first_kept_active_index == 2


def test_scan_does_not_re_mark_lines_a_retract_already_dropped() -> None:
    scan = scan_history(
        _rows(
            _user("old"),
            _user("retracted"),
            message.RetractEntry(retracted_text="retracted", retracted_line=1),
            _user("kept"),
            message.CompactionEntry(summary="s", first_kept_index=2, first_kept_line=3),
        )
    )

    assert _statuses(scan.statuses) == [
        (0, "compacted", 4),
        (1, "retracted", 2),
        (2, "compacted", 4),
        (3, "active", None),
        (4, "active", None),
    ]


def test_scan_marks_the_tail_a_legacy_rewind_discarded() -> None:
    checkpoint = message.DeveloperMessage(
        parts=message.text_parts_from_str("<system-reminder>Checkpoint 0</system-reminder>")
    )
    scan = scan_history(
        _rows(
            _user("before checkpoint"),
            checkpoint,
            _assistant("discarded"),
            _user("also discarded"),
            message.RewindEntry(
                checkpoint_id=0,
                note="n",
                rationale="r",
                reverted_from_index=4,
                original_user_message="before checkpoint",
            ),
        )
    )

    assert scan.active_lines == [0, 1, 4]
    assert _statuses(scan.statuses) == [
        (0, "active", None),
        (1, "active", None),
        (2, "rewound", 4),
        (3, "rewound", 4),
        (4, "active", None),
    ]


def test_rebuild_loaded_history_is_a_thin_wrapper_over_the_scan() -> None:
    raw: list[message.HistoryEvent] = [
        _user("old"),
        _user("dropped"),
        message.RetractEntry(retracted_text="dropped"),
        message.CompactionEntry(summary="s", first_kept_index=1),
    ]

    assert rebuild_loaded_history(raw) == scan_history(list(enumerate(raw))).active
    # The compacted prefix stays: only retracted items leave the active list.
    assert [type(item).__name__ for item in rebuild_loaded_history(raw)] == [
        "UserMessage",
        "RetractEntry",
        "CompactionEntry",
    ]
