from __future__ import annotations

import re
from bisect import bisect_left
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Literal

from klaude_code.prompts.messages import CHECKPOINT_TEMPLATE
from klaude_code.protocol import message
from klaude_code.protocol.models import TaskMetadataItem, Usage

_XML_TAG_RE_CACHE: dict[str, re.Pattern[str]] = {}

# Entries the LLM never sees. They stay in the active list (and therefore in
# ``Session.conversation_history``) but are tagged so ledger views can tell
# them apart from payload lines.
_SIDECAR_ENTRY_TYPES = (
    message.CacheHitRateEntry,
    TaskMetadataItem,
    message.SideQuestionEntry,
    message.SpawnSubAgentEntry,
    message.InterruptEntry,
    message.StreamErrorItem,
    message.AwaySummaryEntry,
    message.PromptSuggestionEntry,
    message.TaskFileChangeSummaryEntry,
    message.FallbackModelConfigWarnEntry,
)

LineStatusName = Literal["active", "retracted", "compacted", "rewound", "unknown", "sidecar"]


@dataclass(frozen=True, slots=True)
class LineStatus:
    """Fate of one physical ``events.jsonl`` line.

    ``dropped_by`` is the line index of the marker entry that invalidated this
    line (``RetractEntry`` / ``CompactionEntry`` / legacy ``RewindEntry``).
    """

    line_index: int
    status: LineStatusName
    dropped_by: int | None = None


@dataclass(slots=True)
class ScanResult:
    """One pass over the raw history lines.

    ``active`` is the in-memory conversation list: raw lines minus the ones a
    retract (or a legacy rewind) removed. Compaction is a *status marking
    only* — compacted lines stay in ``active``; the LLM-facing cut happens at
    request time in ``Session.get_llm_history``.
    """

    active: list[message.HistoryEvent] = field(default_factory=list)  # pyright: ignore[reportUnknownVariableType]
    active_lines: list[int] = field(default_factory=list)  # pyright: ignore[reportUnknownVariableType]
    statuses: list[LineStatus] = field(default_factory=list)  # pyright: ignore[reportUnknownVariableType]
    # Index into ``active`` of the last compaction's first kept item, or None
    # when the session has no compaction. Display-only cut coordinate.
    first_kept_active_index: int | None = None


def extract_xml_tag(text: str, tag: str) -> str:
    """Extract content between ``<tag>...</tag>`` blocks."""
    pattern = _XML_TAG_RE_CACHE.get(tag)
    if pattern is None:
        pattern = re.compile(rf"<{re.escape(tag)}>(.*?)</{re.escape(tag)}>", re.DOTALL)
        _XML_TAG_RE_CACHE[tag] = pattern
    match = pattern.search(text)
    return match.group(1) if match else ""


def find_checkpoint_index_in_history(
    history: Sequence[message.HistoryEvent],
    checkpoint_id: int,
) -> int | None:
    # Legacy: RewindEntry is no longer written; kept so old sessions load.
    target_text = CHECKPOINT_TEMPLATE.format(checkpoint_id=checkpoint_id)
    for idx, item in enumerate(history):
        if not isinstance(item, message.DeveloperMessage):
            continue
        text = message.join_text_parts(item.parts)
        if target_text in text:
            return idx
    return None


def _compaction_cut(
    entry: message.CompactionEntry,
    active_lines: Sequence[int],
    active_len: int,
) -> int:
    """Resolve a compaction boundary to an index into the active list.

    The file line wins when present: it survives retracts and reloads, while
    ``first_kept_index`` is only valid against the list the compaction saw.
    """
    if entry.first_kept_line is not None:
        return bisect_left(active_lines, entry.first_kept_line)
    return min(max(entry.first_kept_index, 0), active_len)


def scan_history(rows: Iterable[tuple[int, message.HistoryEvent | None]]) -> ScanResult:
    """Replay raw history lines into the active list plus per-line statuses.

    ``rows`` yields every physical line in order, with ``None`` for lines that
    failed to decode or carry an unknown ``type``; those keep their line index
    and are reported as ``unknown``.
    """
    result = ScanResult()
    active = result.active
    active_lines = result.active_lines
    statuses = result.statuses
    # line_index -> position in ``statuses`` (rows need not start at 0).
    status_pos: dict[int, int] = {}

    def _mark(line_index: int, status: LineStatusName, dropped_by: int) -> None:
        pos = status_pos.get(line_index)
        if pos is None:
            return
        statuses[pos] = LineStatus(line_index=line_index, status=status, dropped_by=dropped_by)

    def _drop_active(active_index: int, status: LineStatusName, dropped_by: int) -> None:
        line_index = active_lines[active_index]
        del active[active_index]
        del active_lines[active_index]
        _mark(line_index, status, dropped_by)

    def _apply_rewind(entry: message.RewindEntry, line_index: int) -> None:
        # Legacy: RewindEntry is no longer written; kept so old sessions load.
        target_idx = find_checkpoint_index_in_history(active, entry.checkpoint_id)
        if target_idx is None:
            return
        for idx in range(len(active) - 1, target_idx, -1):
            _drop_active(idx, "rewound", line_index)

    def _apply_retract(entry: message.RetractEntry, line_index: int) -> None:
        """Drop the retracted UserMessage, mirroring the live retraction exactly.

        Only the message itself is removed — the turn's other appends
        (attachment developer messages, partial metadata, interrupt entry)
        stay, keeping file-tracker state and token accounting consistent. On an
        anchor mismatch the history is left untouched rather than losing the
        wrong message.
        """
        target_idx: int | None = None
        if entry.retracted_line is not None:
            pos = bisect_left(active_lines, entry.retracted_line)
            if (
                pos < len(active_lines)
                and active_lines[pos] == entry.retracted_line
                and isinstance(active[pos], message.UserMessage)
            ):
                target_idx = pos
        if target_idx is None:
            for idx in range(len(active) - 1, -1, -1):
                item = active[idx]
                if not isinstance(item, message.UserMessage):
                    continue
                if message.join_text_parts(item.parts) == entry.retracted_text:
                    target_idx = idx
                break
        if target_idx is None:
            return
        _drop_active(target_idx, "retracted", line_index)

    def _apply_compaction(entry: message.CompactionEntry, line_index: int) -> None:
        # Status marking only: the summarized prefix stays in the active list
        # and is cut when a request is built. Lines already marked keep their
        # mark — 'retracted'/'rewound' are stronger, 'sidecar' says what the
        # line IS rather than what happened to it.
        cut = _compaction_cut(entry, active_lines, len(active))
        for idx in range(min(cut, len(active))):
            pos = status_pos.get(active_lines[idx])
            if pos is None or statuses[pos].status != "active":
                continue
            statuses[pos] = LineStatus(line_index=active_lines[idx], status="compacted", dropped_by=line_index)

    for line_index, item in rows:
        status_pos[line_index] = len(statuses)
        if item is None:
            statuses.append(LineStatus(line_index=line_index, status="unknown"))
            continue
        statuses.append(
            LineStatus(
                line_index=line_index,
                status="sidecar" if isinstance(item, _SIDECAR_ENTRY_TYPES) else "active",
            )
        )
        if isinstance(item, message.RewindEntry):
            _apply_rewind(item, line_index)
        elif isinstance(item, message.RetractEntry):
            _apply_retract(item, line_index)
        elif isinstance(item, message.CompactionEntry):
            _apply_compaction(item, line_index)
        # Marker entries stay in the active list: indices recorded live, e.g.
        # ``CompactionEntry.first_kept_index``, still line up after a reload.
        active.append(item)
        active_lines.append(line_index)

    for idx in range(len(active) - 1, -1, -1):
        entry = active[idx]
        if isinstance(entry, message.CompactionEntry):
            result.first_kept_active_index = _compaction_cut(entry, active_lines, len(active))
            break

    return result


def rebuild_loaded_history(raw_history: Iterable[message.HistoryEvent]) -> list[message.HistoryEvent]:
    """Active history for a loaded session: raw lines minus retracted ones.

    The compacted prefix is NOT cut here — that keeps loaded coordinates equal
    to live ones (a live session never cuts either), so a compaction recorded
    after a reload still points at the right item. ``get_llm_history`` applies
    the compaction boundary when a request is built.
    """
    return scan_history(enumerate(raw_history)).active


def update_last_request_usage(
    usage: Usage | None,
    history: Iterable[message.HistoryEvent],
) -> Usage | None:
    """Update the latest valid request usage from chronological history entries."""
    for item in history:
        if isinstance(item, (message.CompactionEntry, message.RewindEntry, message.RetractEntry)):
            usage = None
            continue
        if not isinstance(item, message.AssistantMessage):
            continue
        if item.stop_reason in {"aborted", "error"} or item.usage is None:
            usage = None
            continue
        prompt_tokens = max(
            item.usage.input_tokens,
            item.usage.cached_tokens + item.usage.cache_write_tokens,
        )
        usage = item.usage if prompt_tokens > 0 else None
    return usage


def last_request_usage(history: Iterable[message.HistoryEvent]) -> Usage | None:
    """Return the latest valid request usage after the most recent context reset."""
    return update_last_request_usage(None, history)


__all__ = [
    "LineStatus",
    "LineStatusName",
    "ScanResult",
    "extract_xml_tag",
    "find_checkpoint_index_in_history",
    "last_request_usage",
    "rebuild_loaded_history",
    "scan_history",
    "update_last_request_usage",
]
