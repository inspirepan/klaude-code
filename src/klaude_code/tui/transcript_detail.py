"""Transcript detail level: the single source of truth for compact vs full rendering.

Ctrl+O toggles between two renderings of the same event stream, and that choice
reaches three layers -- which commands `DisplayStateMachine` emits, whether
`TUICommandRenderer` prints an event, and which form a component builds. All three
read it from here rather than deciding for themselves:

- `TranscriptDetail` -- one holder, shared by the machine and the renderer.
- `hidden_in` / `is_visible` -- one table for "does this event print at all".
- `Detail` -- passed to components as `detail=` for "how much does it print".

`Detail` is about how much of the transcript is shown. It is a separate axis from
the terminal-width responsiveness in `components/rich/status.py`, which narrows a
single status line -- both can apply at once, so that one is spelled `narrow`.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum

from klaude_code.protocol import events


class Detail(StrEnum):
    """How much of the transcript is rendered."""

    COMPACT = "compact"
    FULL = "full"

    @property
    def is_compact(self) -> bool:
        return self is Detail.COMPACT


class Quadrant(StrEnum):
    """A (detail level, agent kind) pair -- the unit `hidden_in` is keyed by.

    Sub-agent output is the axis that matters most: compact mode replaces a
    sub-agent's per-event transcript with a batched summary, so most events are
    dropped for sub-agents while the same event still prints for the main agent.
    """

    COMPACT_MAIN = "compact/main"
    COMPACT_SUB_AGENT = "compact/sub-agent"
    FULL_MAIN = "full/main"
    FULL_SUB_AGENT = "full/sub-agent"

    @staticmethod
    def of(detail: Detail, *, is_sub_agent: bool) -> Quadrant:
        if detail.is_compact:
            return Quadrant.COMPACT_SUB_AGENT if is_sub_agent else Quadrant.COMPACT_MAIN
        return Quadrant.FULL_SUB_AGENT if is_sub_agent else Quadrant.FULL_MAIN


EVERY_QUADRANT = frozenset(Quadrant)
SUB_AGENT = frozenset({Quadrant.COMPACT_SUB_AGENT, Quadrant.FULL_SUB_AGENT})
COMPACT_SUB_AGENT = frozenset({Quadrant.COMPACT_SUB_AGENT})
ONLY_FULL_SUB_AGENT = EVERY_QUADRANT - {Quadrant.FULL_SUB_AGENT}

# Quadrants in which an event produces no transcript output at all. Events absent
# from this table always print; how *much* they print is the `detail` argument
# threaded into the components, not a visibility question.
_HIDDEN_IN: Mapping[type[events.Event], frozenset[Quadrant]] = {
    # A compact sub-agent transcript is replaced wholesale by the batch summary
    # `DisplayStateMachine._maybe_finish_sub_agent_batch` emits once the batch ends.
    events.ToolCallEvent: COMPACT_SUB_AGENT,
    events.DeveloperMessageEvent: COMPACT_SUB_AGENT,
    events.NoticeEvent: COMPACT_SUB_AGENT,
    events.AwaySummaryEvent: COMPACT_SUB_AGENT,
    events.SessionStatsEvent: COMPACT_SUB_AGENT,
    events.ContextUsageEvent: COMPACT_SUB_AGENT,
    events.ErrorEvent: COMPACT_SUB_AGENT,
    # Task boundaries are only ever drawn for a sub-agent, and only expanded: the
    # main agent's own start/finish is implied by the surrounding prompt.
    events.TaskStartEvent: ONLY_FULL_SUB_AGENT,
    events.TaskFinishEvent: ONLY_FULL_SUB_AGENT,
    # Usage and file-change totals are reported once, by the parent task.
    events.TaskMetadataEvent: SUB_AGENT,
    events.TaskFileChangeSummaryEvent: SUB_AGENT,
    # These two are asked at the state-machine layer rather than the renderer:
    # they reach the renderer as commands carrying only a summary, with no event
    # left to consult. The other quadrants still render something (a summary line
    # for compact, a panel or a live stream for full).
    events.CompactionEndEvent: COMPACT_SUB_AGENT,
    events.ThinkingEndEvent: COMPACT_SUB_AGENT,
}


def hidden_in(event_type: type[events.Event]) -> frozenset[Quadrant]:
    """Quadrants where `event_type` is dropped from the transcript."""
    return _HIDDEN_IN.get(event_type, frozenset())


def listed_event_types() -> frozenset[type[events.Event]]:
    """Event classes the table has an opinion about; everything else always prints."""
    return frozenset(_HIDDEN_IN)


def is_visible(event: events.Event, *, detail: Detail, is_sub_agent: bool) -> bool:
    """Whether `event` reaches the transcript at this detail level."""
    return Quadrant.of(detail, is_sub_agent=is_sub_agent) not in hidden_in(type(event))


class TranscriptDetail:
    """Mutable holder shared by the state machine and the renderer.

    Both layers branch on the level and they have to agree: a replay rendered at
    one level while the machine emits commands for the other paints a mixed
    transcript. Sharing one object removes the chance of the two drifting.
    """

    def __init__(self, detail: Detail = Detail.COMPACT) -> None:
        self._detail = detail

    @property
    def current(self) -> Detail:
        return self._detail

    @property
    def is_compact(self) -> bool:
        return self._detail.is_compact

    def set(self, detail: Detail) -> None:
        self._detail = detail

    def toggle(self) -> Detail:
        self._detail = Detail.FULL if self._detail.is_compact else Detail.COMPACT
        return self._detail


def _validate_table() -> None:
    """Reject a table entry that can never fire, at import time.

    Mirrors `DisplayStateMachine._EVENT_HANDLERS` validation: a typo'd or
    fully-hidden entry is a silent bug otherwise.
    """
    for event_cls, quadrants in _HIDDEN_IN.items():
        if not isinstance(event_cls, type) or not issubclass(event_cls, events.Event):
            raise RuntimeError(f"transcript detail table key {event_cls!r} is not an events.Event subclass")
        if not quadrants:
            raise RuntimeError(f"{event_cls.__name__} maps to no quadrant; drop the entry instead")
        if quadrants == EVERY_QUADRANT:
            raise RuntimeError(f"{event_cls.__name__} is hidden everywhere; stop emitting the command instead")


_validate_table()
