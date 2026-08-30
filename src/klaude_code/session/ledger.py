"""Turn and step ordinals for ledger readers.

``events.jsonl`` is a flat line log with no notion of a "turn". A reader that
pages through it must not derive ordinals from the page it happens to hold --
prepending an older page would renumber everything -- so the numbering is
computed here in one pass over the whole file and served as absolute values
(``server/routes/web_api.py``).

A *turn* is opened by a human user message. The runtime also appends
``UserMessage`` lines nobody typed (bash-mode echoes, retry continuations, the
fork-context reminder a forked sub-agent session is seeded with); those belong
to the turn they were injected into and never open one. The rules live here so
the classification has exactly one definition.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from klaude_code.prompts.messages import EMPTY_RESPONSE_CONTINUATION_PROMPT, STREAM_ERROR_CONTINUATION_REMINDER
from klaude_code.prompts.sub_agents import FORK_CONTEXT_GENERAL_PROMPT, FORK_CONTEXT_WITH_ROLE_PROMPT
from klaude_code.protocol import message

# ``agent/step.py`` wraps the partial output in <assistant>...</assistant> and
# appends the reminder, so only the tail is a fixed string.
_STREAM_ERROR_PREFIX = "<assistant>"
# ``agent/runtime/sub_agent.py`` wraps either fork-context prompt in a system
# reminder; the role variant is a prefix (the role prompt follows it).
_FORK_CONTEXT_PREFIXES = (
    f"<system-reminder>{FORK_CONTEXT_WITH_ROLE_PROMPT}",
    f"<system-reminder>{FORK_CONTEXT_GENERAL_PROMPT}",
)


@dataclass(frozen=True, slots=True)
class LineOrdinal:
    """Where one physical line sits in the turn/step numbering.

    ``turn_index`` is 1-based; lines ahead of the first human user message get
    0. ``step_index`` is 1-based within the turn and set on ``AssistantMessage``
    lines only. ``auto`` is set on ``UserMessage`` lines only, and is True when
    the runtime injected the message rather than a person typing it.
    """

    turn_index: int
    step_index: int | None = None
    auto: bool | None = None


_UNPLACED: LineOrdinal = LineOrdinal(turn_index=0)


@dataclass(slots=True)
class TurnOrdinals:
    """Ordinals for every physical line, plus the file's human turn count."""

    by_line: dict[int, LineOrdinal] = field(default_factory=dict)  # pyright: ignore[reportUnknownVariableType]
    turn_count: int = 0

    def for_line(self, line_index: int) -> LineOrdinal:
        return self.by_line.get(line_index, _UNPLACED)


def is_auto_user_message(item: message.UserMessage) -> bool:
    """True when the runtime, not a person, produced this user message."""
    if item.source == "bash_mode":
        return True
    text = message.join_text_parts(item.parts).strip()
    if not text:
        return False
    if text == EMPTY_RESPONSE_CONTINUATION_PROMPT:
        return True
    if text.startswith(_STREAM_ERROR_PREFIX) and text.endswith(STREAM_ERROR_CONTINUATION_REMINDER):
        return True
    return text.startswith(_FORK_CONTEXT_PREFIXES)


def scan_turn_ordinals(rows: Iterable[tuple[int, message.HistoryEvent | None]]) -> TurnOrdinals:
    """Number every physical line by its turn, in one pass over the file.

    ``rows`` yields every line in order, with ``None`` for lines that failed to
    decode; those keep the ordinals of the turn they sit in. A
    ``ForkSummaryEntry`` is a row of its own and does not open a turn, even
    though other views project it to a ``UserMessage``.
    """
    result = TurnOrdinals()
    turn_index = 0
    step_index = 0
    for line_index, item in rows:
        auto: bool | None = None
        step: int | None = None
        if isinstance(item, message.UserMessage):
            auto = is_auto_user_message(item)
            if not auto:
                turn_index += 1
                step_index = 0
        elif isinstance(item, message.AssistantMessage):
            step_index += 1
            step = step_index
        result.by_line[line_index] = LineOrdinal(turn_index=turn_index, step_index=step, auto=auto)
    result.turn_count = turn_index
    return result


__all__ = [
    "LineOrdinal",
    "TurnOrdinals",
    "is_auto_user_message",
    "scan_turn_ordinals",
]
