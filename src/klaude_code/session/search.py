"""Full-text search over a session's raw ``events.jsonl`` lines.

The web viewer filters the rows it already holds on the client; this module
covers the lines it has *not* loaded, so a hit can be reported as a
``line_index`` the client jumps to (``server/routes/web_api.py``).

The searchable text of a line is the concatenation of its entry's text-bearing
fields plus the entry type name and any tool/call ids, which mirrors what the
client indexes -- a server hit is therefore also a client hit once that page is
on screen. Image and binary parts carry nothing to match on.

One pass over the decoded rows of a 20 MB / 6k-line session costs ~30 ms, so
nothing is cached here: the decode cache the pass reads (``store.py``) is the
expensive part and it is already shared with the paging endpoints.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, field

from klaude_code.protocol import message
from klaude_code.protocol.models import TaskMetadataItem

# Fields are joined by a newline so a term can never match across two of them.
_FIELD_SEP = "\n"

MAX_QUERY_CHARS = 500
SNIPPET_CHARS = 160
_ELLIPSIS = "…"


@dataclass(frozen=True, slots=True)
class LineHit:
    """One matching physical line, with its text kept for the snippet."""

    line_index: int
    kind: str
    text: str


@dataclass(slots=True)
class SearchScan:
    """Result of one pass over a session's lines.

    ``total`` counts every match; ``hits`` holds at most the requested limit,
    ascending by line index.
    """

    total: int = 0
    hits: list[LineHit] = field(default_factory=list)  # pyright: ignore[reportUnknownVariableType]


def split_terms(query: str) -> list[str]:
    """Lowercased whitespace-split terms, AND-matched against a line."""
    return query.strip().lower().split()


def line_search_text(item: message.HistoryEvent) -> str:
    """Everything of one entry a query may match, in its original case."""
    return _FIELD_SEP.join(chunk for chunk in _iter_chunks(item) if chunk)


def scan_search(
    rows: Iterable[tuple[int, message.HistoryEvent | None]],
    terms: Sequence[str],
    limit: int,
) -> SearchScan:
    """Find the lines whose searchable text contains every term.

    Undecodable lines are skipped: they have no fields to match. Discarded
    lines (compacted/retracted/rewound) are not — the caller reports their
    status so the client can grey them out.
    """
    result = SearchScan()
    if not terms:
        return result
    for line_index, item in rows:
        if item is None:
            continue
        text = line_search_text(item)
        lowered = text.lower()
        if not all(term in lowered for term in terms):
            continue
        result.total += 1
        if len(result.hits) < limit:
            result.hits.append(LineHit(line_index=line_index, kind=type(item).__name__, text=text))
    return result


def snippet_for(text: str, terms: Sequence[str], *, width: int = SNIPPET_CHARS) -> str:
    """One line of at most ``width`` chars around the first term hit.

    The ellipsis markers count against ``width``, and runs of whitespace are
    collapsed, so the result always fits a single row of the result list.
    """
    lowered = text.lower()
    # `str.lower()` can change length for a few code points; fall back to the
    # lowered text so the window stays aligned with the position we found.
    source = text if len(lowered) == len(text) else lowered
    hits = [pos for pos in (lowered.find(term) for term in terms) if pos >= 0]
    # Leave the hit a third of the way in so its lead-in stays visible.
    begin = max(min(hits, default=0) - width // 3, 0)
    prefix = _ELLIPSIS if begin > 0 else ""
    end = begin + width - len(prefix)
    suffix = _ELLIPSIS if end < len(source) else ""
    window = " ".join(source[begin : end - len(suffix)].split())
    return f"{prefix}{window}{suffix}" if window else ""


def _iter_chunks(item: message.HistoryEvent) -> Iterator[str]:
    # The type name is searchable so a query can name the kind of a row.
    yield type(item).__name__
    match item:
        case message.SystemMessage() | message.DeveloperMessage() | message.UserMessage() | message.AssistantMessage():
            yield from _iter_part_chunks(item.parts)
        case message.ToolResultMessage():
            yield item.tool_name
            yield item.call_id
            yield item.output_text
        case message.StreamErrorItem():
            yield item.error
        case message.CompactionEntry():
            yield item.summary
        case message.RewindEntry():
            yield item.note
            yield item.rationale
            yield item.original_user_message
        case message.RetractEntry():
            yield item.retracted_text
        case message.AwaySummaryEntry() | message.PromptSuggestionEntry():
            yield item.text
        case message.SideQuestionEntry():
            yield item.question
            yield item.answer
        case message.ForkSummaryEntry():
            yield item.summary
        case message.SpawnSubAgentEntry():
            yield item.sub_agent_type
            yield item.sub_agent_desc
            yield item.session_id
        case message.FallbackModelConfigWarnEntry():
            yield item.from_model
            yield item.to_model
            yield item.reason
        case message.LLMRequestEntry():
            yield item.request_id
            yield item.kind
            yield item.label or ""
            yield item.provider or ""
            yield item.model or ""
            yield item.error or ""
        case message.TaskFileChangeSummaryEntry():
            for change in item.files:
                yield change.path
        case TaskMetadataItem() | message.CacheHitRateEntry() | message.InterruptEntry():
            # Numbers and flags only: nothing beyond the type name to match on.
            pass


def _iter_part_chunks(parts: Sequence[message.Part]) -> Iterator[str]:
    for part in parts:
        match part:
            case message.TextPart() | message.ThinkingTextPart():
                yield part.text
            case message.ToolCallPart():
                yield part.tool_name
                yield part.call_id
                yield part.arguments_json
            case _:
                # Image parts and thinking signatures carry no readable text.
                pass


__all__ = [
    "MAX_QUERY_CHARS",
    "SNIPPET_CHARS",
    "LineHit",
    "SearchScan",
    "line_search_text",
    "scan_search",
    "snippet_for",
    "split_terms",
]
