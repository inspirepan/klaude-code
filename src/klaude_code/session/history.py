from __future__ import annotations

import re
from collections.abc import Iterable, Sequence

from klaude_code.prompts.messages import CHECKPOINT_TEMPLATE
from klaude_code.protocol import message
from klaude_code.protocol.models import Usage

_CHECKPOINT_RE = re.compile(r"<system-reminder>Checkpoint (\d+)</system-reminder>")
_XML_TAG_RE_CACHE: dict[str, re.Pattern[str]] = {}


def extract_xml_tag(text: str, tag: str) -> str:
    """Extract content between ``<tag>...</tag>`` blocks."""
    pattern = _XML_TAG_RE_CACHE.get(tag)
    if pattern is None:
        pattern = re.compile(rf"<{re.escape(tag)}>(.*?)</{re.escape(tag)}>", re.DOTALL)
        _XML_TAG_RE_CACHE[tag] = pattern
    match = pattern.search(text)
    return match.group(1) if match else ""


def extract_checkpoint_id(text: str) -> int | None:
    match = _CHECKPOINT_RE.search(text)
    if match is None:
        return None
    return int(match.group(1))


def find_checkpoint_index_in_history(
    history: Sequence[message.HistoryEvent],
    checkpoint_id: int,
) -> int | None:
    target_text = CHECKPOINT_TEMPLATE.format(checkpoint_id=checkpoint_id)
    for idx, item in enumerate(history):
        if not isinstance(item, message.DeveloperMessage):
            continue
        text = message.join_text_parts(item.parts)
        if target_text in text:
            return idx
    return None


def _apply_rewind_entry_to_history(
    history: list[message.HistoryEvent],
    entry: message.RewindEntry,
) -> list[message.HistoryEvent]:
    target_idx = find_checkpoint_index_in_history(history, entry.checkpoint_id)
    if target_idx is None:
        return [*history, entry]
    return [*history[: target_idx + 1], entry]


def _apply_retract_entry_to_history(
    history: list[message.HistoryEvent],
    entry: message.RetractEntry,
) -> list[message.HistoryEvent]:
    """Drop the retracted UserMessage, mirroring the live retraction exactly.

    Only the message itself is removed — the turn's other appends (attachment
    developer messages, partial metadata, interrupt entry) stay, keeping
    file-tracker state and token accounting consistent. The entry is kept in
    active history (like RewindEntry) so indices recorded live, e.g.
    ``CompactionEntry.first_kept_index``, still line up after a reload. On an
    anchor mismatch the history is left untouched rather than losing the
    wrong message.
    """
    for idx in range(len(history) - 1, -1, -1):
        item = history[idx]
        if not isinstance(item, message.UserMessage):
            continue
        if message.join_text_parts(item.parts) == entry.retracted_text:
            return [*history[:idx], *history[idx + 1 :], entry]
        break
    return [*history, entry]


def rebuild_loaded_history(raw_history: Iterable[message.HistoryEvent]) -> list[message.HistoryEvent]:
    active_history: list[message.HistoryEvent] = []
    for item in raw_history:
        if isinstance(item, message.RewindEntry):
            active_history = _apply_rewind_entry_to_history(active_history, item)
            continue
        if isinstance(item, message.RetractEntry):
            active_history = _apply_retract_entry_to_history(active_history, item)
            continue
        active_history.append(item)

    last_compaction: message.CompactionEntry | None = None
    for item in reversed(active_history):
        if isinstance(item, message.CompactionEntry):
            last_compaction = item
            break

    if last_compaction is None:
        return active_history

    cut_index = min(max(last_compaction.first_kept_index, 0), len(active_history))
    kept = [item for item in active_history[cut_index:] if not isinstance(item, message.CompactionEntry)]
    normalized_compaction = last_compaction.model_copy(update={"first_kept_index": 1})
    return [normalized_compaction, *kept]


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
    "extract_checkpoint_id",
    "extract_xml_tag",
    "find_checkpoint_index_in_history",
    "last_request_usage",
    "rebuild_loaded_history",
    "update_last_request_usage",
]
