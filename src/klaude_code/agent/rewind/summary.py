"""Summary generation for the user-facing `/rewind` command.

Writes the fork-summary request. Two paths:

- Cache-sharing fork (preferred): the request wire is the session's FULL
  LLM-facing history (``get_llm_history()``) plus a trailing instruction
  message. The prefix is byte-identical to the parent's most recent request,
  so the server-side prompt cache is reused up to the end of the kept tail.
  Requires the summarizer client to share the main profile's cache key (see
  ``is_cache_sharable``).
- Fallback: the tail ``[pivot..end]`` is serialized into a standalone request
  on the summarizer client. No cache reuse; summary format is preserved.

See ``agent/rewind/AGENTS.md`` for the two-rewind vocabulary rules.
"""

import asyncio
from dataclasses import dataclass

from klaude_code.agent.agent_profile import AgentProfile
from klaude_code.agent.cache_safe import CacheSafeParams, build_cache_safe_messages, is_cache_sharable
from klaude_code.agent.compaction.compaction import serialize_conversation
from klaude_code.llm import LLMClientABC
from klaude_code.prompts.compaction import FORK_SUMMARY_USER_PREFIX, build_fork_summary_prompt
from klaude_code.protocol import llm_param, message
from klaude_code.protocol.models import Usage
from klaude_code.session.session import Session

# The 9-section detailed summary needs more output headroom than the compact
# compaction summary. max_tokens does not enter the cache key on the fork path.
REWIND_SUMMARY_MAX_TOKENS = 16384

_PIVOT_QUOTE_MAX_CHARS = 400


@dataclass(frozen=True)
class RewindSummaryResult:
    text: str
    message_count: int
    tokens_before: int | None
    cache_hit_rate: float | None
    fallback_used: bool


def count_summarized_messages(history: list[message.HistoryEvent], pivot_index: int) -> int:
    """Number of LLM-facing messages the rewind discards: ``[pivot..end]``.

    ``pivot_index == -1`` (rewind entire conversation) counts everything.
    Operates on the SAME view the pivot index was resolved against (see
    :func:`active_history`); ForkSummaryEntry counts as one message because it
    projects into the LLM view.
    """

    return len(_tail_items(history, pivot_index))


def _tail_items(history: list[message.HistoryEvent], pivot_index: int) -> list[message.HistoryEvent]:
    start = 0 if pivot_index < 0 else pivot_index
    return history[start:]


def _tail_messages(history: list[message.HistoryEvent], pivot_index: int) -> list[message.Message]:
    """LLM-facing messages of the discarded tail.

    ForkSummaryEntry projects to its UserMessage form so a re-rewound session
    keeps the earlier summary in the serialized fallback path (the
    cache-sharing fork path covers it via ``get_llm_history`` instead).
    """

    out: list[message.Message] = []
    for item in _tail_items(history, pivot_index):
        if isinstance(item, message.SystemMessage):
            continue
        if isinstance(item, message.Message):
            out.append(item)
        elif isinstance(item, message.ForkSummaryEntry):
            out.append(message.UserMessage(parts=[message.TextPart(text=FORK_SUMMARY_USER_PREFIX + item.summary)]))
    return out


def _pivot_text(history: list[message.HistoryEvent], pivot_index: int) -> str:
    """Verbatim quote of the pivot user message for boundary anchoring."""

    if 0 <= pivot_index < len(history):
        item = history[pivot_index]
        if isinstance(item, message.UserMessage):
            text = message.join_text_parts(item.parts).strip()
            if text:
                if len(text) > _PIVOT_QUOTE_MAX_CHARS:
                    text = text[:_PIVOT_QUOTE_MAX_CHARS] + "...(truncated)"
                return text
    return "(session start)"


def build_rewind_instruction(history: list[message.HistoryEvent], pivot_index: int) -> message.UserMessage:
    """Trailing instruction message for the cache-sharing fork request."""

    prompt_text = build_fork_summary_prompt(pivot_text=_pivot_text(history, pivot_index))
    return message.UserMessage(parts=[message.TextPart(text=prompt_text)])


def _cache_hit_rate(usage: Usage | None) -> float | None:
    if usage is None:
        return None
    # Same cross-provider normalization as CacheTracker / build_fork_cache_event.
    total = max(usage.input_tokens, usage.cached_tokens + usage.cache_write_tokens)
    return usage.cached_tokens / total if total > 0 else None


async def _collect_text(
    llm_client: LLMClientABC, call_param: llm_param.LLMCallParameter
) -> tuple[str, message.AssistantMessage | None]:
    stream = await llm_client.call(call_param)
    accumulated: list[str] = []
    final_message: message.AssistantMessage | None = None
    async for item in stream:
        if isinstance(item, message.AssistantTextDelta):
            accumulated.append(item.content)
        elif isinstance(item, message.StreamErrorItem):
            raise RuntimeError(item.error)
        elif isinstance(item, message.AssistantMessage):
            final_message = item
    text = message.join_text_parts(final_message.parts) if final_message else "".join(accumulated)
    if not text.strip():
        raise ValueError("Rewind summarizer returned empty output")
    return text.strip(), final_message


async def run_rewind_summary(
    *,
    session: Session,
    active_view: list[message.HistoryEvent],
    pivot_index: int,
    llm_client: LLMClientABC,
    main_profile: AgentProfile,
    tokens_before: int | None,
    cancel: asyncio.Event | None = None,
) -> RewindSummaryResult:
    """Generate the rewind summary for ``[pivot..end]`` of the active view.

    ``active_view`` is the rebuilt view the caller resolved the pivot against
    (``Session.load``-equivalent — the caller must NOT rebuild the live list,
    whose in-place rewind/retract mutations make ``rebuild_loaded_history``
    non-idempotent). The cache-sharing fork prefix is the session's full
    LLM-facing history, so the server-side prompt cache is reused up to the
    end of the kept tail when the compact client shares the main profile's
    cache key (``is_cache_sharable``); otherwise the tail is serialized into
    a standalone request.
    """
    if cancel is not None and cancel.is_set():
        raise asyncio.CancelledError

    history = active_view
    message_count = count_summarized_messages(history, pivot_index)
    if message_count == 0:
        raise ValueError("Nothing to summarize after the selected message")

    if is_cache_sharable(main_profile, llm_client):
        cache_safe = CacheSafeParams(
            profile=main_profile,
            prefix_messages=session.get_llm_history(),
            prompt_cache_key=session.prompt_cache_key,
        )
        wire_messages = build_cache_safe_messages(cache_safe, [build_rewind_instruction(history, pivot_index)])
        input_messages = [m for m in wire_messages if isinstance(m, message.Message)]
        call_param = llm_param.LLMCallParameter(
            input=input_messages,
            system=main_profile.system_prompt,
            session_id=session.id,
            prompt_cache_key=cache_safe.prompt_cache_key,
        )
        call_param.tools = main_profile.tools  # Must match parent; tools=[] would break cache.
        call_param.max_tokens = REWIND_SUMMARY_MAX_TOKENS
        text, final_message = await _collect_text(llm_client, call_param)
        return RewindSummaryResult(
            text=text,
            message_count=message_count,
            tokens_before=tokens_before,
            cache_hit_rate=_cache_hit_rate(final_message.usage if final_message else None),
            fallback_used=False,
        )

    # Fallback: serialized standalone request on the summarizer client. No
    # cache prefix to protect, so only the output budget is set.
    prompt_text = build_fork_summary_prompt(pivot_text=_pivot_text(history, pivot_index), inline_conversation=True)
    input_messages: list[message.Message] = [
        message.UserMessage(
            parts=[
                message.TextPart(
                    text=f"<conversation>\n{serialize_conversation(_tail_messages(history, pivot_index))}\n</conversation>\n\n"
                ),
                message.TextPart(text=prompt_text),
            ]
        )
    ]
    call_param = llm_param.LLMCallParameter(
        input=input_messages,
        session_id=session.id,
    )
    call_param.max_tokens = REWIND_SUMMARY_MAX_TOKENS
    text, _ = await _collect_text(llm_client, call_param)
    return RewindSummaryResult(
        text=text,
        message_count=message_count,
        tokens_before=tokens_before,
        cache_hit_rate=None,
        fallback_used=True,
    )
