from __future__ import annotations

import re
from collections.abc import Iterable, Sequence

from klaude_code.prompts.messages import CHECKPOINT_TEMPLATE
from klaude_code.protocol import message

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


def rebuild_loaded_history(raw_history: Iterable[message.HistoryEvent]) -> list[message.HistoryEvent]:
    active_history: list[message.HistoryEvent] = []
    for item in raw_history:
        if isinstance(item, message.RewindEntry):
            active_history = _apply_rewind_entry_to_history(active_history, item)
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


__all__ = [
    "extract_checkpoint_id",
    "extract_xml_tag",
    "find_checkpoint_index_in_history",
    "rebuild_loaded_history",
]
