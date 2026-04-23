"""Prompt-suggestion generator (forked LLM query, cache-shared with main turn).

After every task finishes, predict what the user might naturally type next.
Mirrors claude-code's promptSuggestion service: short single-turn LLM call
with the main profile's system/tools/model/thinking, so the wire prefix
equals the parent turn's wire prefix and cache read hits ~100%.

The model is instructed to reply with exactly ``[DONE]`` when it has nothing
worth suggesting; we filter that plus a small set of low-quality patterns
(evaluative, assistant-voice, multi-sentence, formatting).
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass

from klaude_code.agent.agent_profile import AgentProfile
from klaude_code.agent.cache_safe import CacheSafeParams, build_cache_safe_messages
from klaude_code.log import DebugType, log_debug
from klaude_code.prompts.prompt_suggestion import PROMPT_SUGGESTION_PROMPT
from klaude_code.protocol import llm_param, message
from klaude_code.session.session import Session

# Reasoning models (for example gpt-5.4) may spend most of a tiny budget on
# thinking, leaving no visible suggestion text in the final output.
_MAX_SUGGESTION_TOKENS = 4096
_MIN_ASSISTANT_TURNS = 2

# Cache cold heuristic: if the parent response's own output + uncached input
# exceeds this, the fork has to re-process a lot of un-cached tokens too.
# Skip generation to avoid paying for it just to get a single suggestion.
_MAX_PARENT_UNCACHED_TOKENS = 10_000


@dataclass(frozen=True)
class PromptSuggestionResult:
    suggestion: str | None
    raw: str
    drop_reason: str | None = None


def should_suggest(session: Session) -> str | None:
    """Return a suppression reason or ``None`` when generation is allowed.

    Matches claude-code's guard chain:
    - Too early: <2 assistant turns.
    - Last assistant errored/aborted: do not suggest on unclear state.
    - Cache cold: parent response output + uncached input > 10k tokens.
    """
    history = session.conversation_history
    assistant_count = sum(1 for it in history if isinstance(it, message.AssistantMessage))
    if assistant_count < _MIN_ASSISTANT_TURNS:
        return "early_conversation"

    last_assistant: message.AssistantMessage | None = None
    for item in reversed(history):
        if isinstance(item, message.AssistantMessage):
            last_assistant = item
            break
    if last_assistant is None:
        return "no_assistant"
    if last_assistant.stop_reason in {"error", "aborted"}:
        return "last_response_error"

    usage = last_assistant.usage
    if usage is not None:
        # Cache-cold budget, matching claude-code's getParentCacheSuppressReason:
        # skip when the parent turn had to do a lot of fresh (un-cached) work,
        # because the fork inherits similar cost.
        #
        # Providers disagree on ``Usage.input_tokens`` semantics (Anthropic raw =
        # un-cached only; OpenAI-compat = total including cached). Use the same
        # robust normalization as CacheTracker: ``max(input_tokens, cached +
        # cache_write)`` approximates the total prompt size across providers.
        total_input = max(
            usage.input_tokens,
            usage.cached_tokens + usage.cache_write_tokens,
        )
        uncached = max(0, total_input - usage.cached_tokens) + usage.output_tokens
        if uncached > _MAX_PARENT_UNCACHED_TOKENS:
            return f"cache_cold(uncached={uncached})"
    return None


async def run_prompt_suggestion(
    *,
    session: Session,
    main_profile: AgentProfile,
    cancel: asyncio.Event | None = None,
) -> PromptSuggestionResult | None:
    """Ask the main LLM to predict the user's next prompt.

    Returns a result object after a successful model call, or ``None`` when the
    call/stream failed before a usable response was produced.

    The wire prefix equals ``session.get_llm_history()`` (parent's most recent
    request), and the appended UserMessage is the suggestion instruction.
    tools/system/thinking come from ``main_profile`` — must not be changed
    here or cache will miss.
    """
    if cancel is not None and cancel.is_set():
        raise asyncio.CancelledError

    prefix = session.get_llm_history()
    extra: list[message.HistoryEvent] = [message.UserMessage(parts=[message.TextPart(text=PROMPT_SUGGESTION_PROMPT)])]
    cache_safe = CacheSafeParams(profile=main_profile, prefix_messages=prefix)
    wire = build_cache_safe_messages(cache_safe, extra)
    input_messages = [m for m in wire if isinstance(m, message.Message)]

    call_param = llm_param.LLMCallParameter(
        input=input_messages,
        system=main_profile.system_prompt,
        session_id=session.id,
    )
    # tools must match parent; tools=[] would bust cache (0% hit).
    call_param.tools = main_profile.tools
    call_param.max_tokens = _MAX_SUGGESTION_TOKENS

    try:
        stream = await main_profile.llm_client.call(call_param)
    except Exception as exc:
        log_debug(f"[PromptSuggestion] call failed: {exc}", debug_type=DebugType.RESPONSE)
        return None

    accumulated: list[str] = []
    final_message: message.AssistantMessage | None = None
    try:
        async for item in stream:
            if isinstance(item, message.AssistantTextDelta):
                accumulated.append(item.content)
            elif isinstance(item, message.StreamErrorItem):
                log_debug(f"[PromptSuggestion] stream error: {item.error}", debug_type=DebugType.RESPONSE)
                return None
            elif isinstance(item, message.AssistantMessage):
                final_message = item
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        log_debug(f"[PromptSuggestion] stream failed: {exc}", debug_type=DebugType.RESPONSE)
        return None

    if cancel is not None and cancel.is_set():
        raise asyncio.CancelledError

    raw = message.join_text_parts(final_message.parts) if final_message else "".join(accumulated)
    usage = final_message.usage if final_message else None
    if usage is not None:
        total = usage.cached_tokens + usage.cache_write_tokens + usage.input_tokens
        hit = (usage.cached_tokens / total) if total > 0 else 0.0
        log_debug(
            f"[PromptSuggestion] usage cache_hit={hit:.2%} "
            f"read={usage.cached_tokens} write={usage.cache_write_tokens} "
            f"input={usage.input_tokens} output={usage.output_tokens}",
            debug_type=DebugType.RESPONSE,
        )
    result = _finalize_result(raw)
    if result.suggestion is None and result.drop_reason == "done_or_empty":
        log_debug("[PromptSuggestion] filtered ([DONE] or empty)", raw, debug_type=DebugType.RESPONSE)
        return result
    if result.drop_reason is not None:
        log_debug(
            f"[PromptSuggestion] filtered ({result.drop_reason})",
            result.suggestion or result.raw,
            debug_type=DebugType.RESPONSE,
        )
        return result
    assert result.suggestion is not None
    log_debug("[PromptSuggestion] accepted", result.suggestion, debug_type=DebugType.RESPONSE)
    return result


_DONE_RE = re.compile(r"^\s*\[\s*done\s*\]\s*$", re.IGNORECASE)
_EVALUATIVE_RE = re.compile(
    r"\b(thanks?|thank you|looks good|sounds good|that works|that worked|nice|great|perfect|awesome|excellent)\b",
    re.IGNORECASE,
)
_ASSISTANT_VOICE_RE = re.compile(
    r"^(let me\b|i'?ll\b|i'?ve\b|i'?m\b|i can\b|i would\b|i think\b|i notice\b|here'?s\b|"
    r"here is\b|here are\b|that'?s\b|this is\b|this will\b|you can\b|you should\b|you could\b|"
    r"sure,|of course|certainly)",
    re.IGNORECASE,
)
_MULTI_SENTENCE_RE = re.compile(r"[.!?]\s+[A-Z]")
_FORMATTING_RE = re.compile(r"[\n*]|\*\*")


def _normalize(raw: str) -> str | None:
    """Strip whitespace/quotes, collapse to single line, return None if empty or [DONE]."""
    text = raw.strip().strip("\"'`“”‘’")
    if not text:
        return None
    if _DONE_RE.match(text):
        return None
    return text


def _filter_reason(suggestion: str) -> str | None:
    """Return a filter reason for low-quality suggestions, or None to accept."""
    word_count = len(suggestion.split())
    if word_count > 12:
        return "too_many_words"
    if len(suggestion) >= 100:
        return "too_long"
    if _MULTI_SENTENCE_RE.search(suggestion):
        return "multiple_sentences"
    if _FORMATTING_RE.search(suggestion):
        return "has_formatting"
    if _EVALUATIVE_RE.search(suggestion):
        return "evaluative"
    if _ASSISTANT_VOICE_RE.match(suggestion):
        return "assistant_voice"
    return None


def _finalize_result(raw: str) -> PromptSuggestionResult:
    suggestion = _normalize(raw)
    if suggestion is None:
        return PromptSuggestionResult(suggestion=None, raw=raw, drop_reason="done_or_empty")

    reason = _filter_reason(suggestion)
    if reason is not None:
        return PromptSuggestionResult(suggestion=None, raw=raw, drop_reason=reason)

    return PromptSuggestionResult(suggestion=suggestion, raw=raw)
